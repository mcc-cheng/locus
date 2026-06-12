"""The analyst agent — a multi-step, tool-using LLM over your data.

Each turn the agent runs a short ReAct loop on a local Ollama model: it inspects
a rich description of the datasets, issues validated read-only tools (SQL,
charts, statistics), observes the results, iterates, and finally writes a fluent,
streamed natural-language answer grounded in what it actually found.

Security is unchanged from the strict design: every tool call is validated and
executed through the read-only services (SELECT-only queries, server-aggregated
charts) or a disposable sandbox (statistics). The model never touches data
directly and can never modify the canonical warehouse.

``run()`` yields events for streaming; ``handle()`` collects a turn for tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from executor import SandboxManager, run_script
from ingest.errors import OllamaUnavailableError
from services import (
    ChartRequest,
    QueryService,
    SchemaService,
    ServiceError,
    VisualizationService,
)

from .brain import AgentError, Brain
from .stats import build_stat_script, parse_stat_output
from .steps import Answer, MakeChart, RunSql, RunStat

MAX_STEPS = 6
_PREVIEW_ROWS = 20
_CELL = 60

_TOOLS_DOC = """\
You are Locus's data analyst. You help a scientist understand their datasets by
exploring the data yourself before answering. You have READ-ONLY access — you can
never change the data.

Each turn, respond with JSON: {"thought": "...", "step": {...}}. Choose ONE step:

- run_sql:    {"kind":"run_sql","sql":"SELECT ... "}
    Explore the data with a single read-only SELECT. Use fully-qualified names
    like "section"."table". Prefer the verbatim "raw" table. SELECT only.
- make_chart: {"kind":"make_chart","chart_type":"histogram|bar|heatmap|dose_response|scatter",
               "section":"...","table":"raw","x":"col","y":"col","color":"col",...}
    Build a chart (aggregated on the server) when a visual answer helps.
- run_stat:   {"kind":"run_stat","test":"ttest_ind|pearsonr|...","section":"...",
               "table":"raw","columns":["a","b"],"group_by":"col"}
    Run a statistical test in a sandbox.
- answer:     {"kind":"answer"}
    Stop exploring and write the final answer.

Guidance: run one or two queries to get the real numbers, then answer. Always use
columns that exist. When the user asks for a chart, use make_chart. When they ask
whether groups differ or whether things correlate, use run_stat. Don't loop more
than necessary.
"""

_ANSWER_SYSTEM = """\
You are Locus's data analyst. Using ONLY the observations gathered above (query
results, charts, statistics), write a clear, concise answer to the user's latest
question. Cite the concrete numbers you found. If you created a chart, mention it.
Do not invent data you did not observe. Use short paragraphs or bullet points.
"""


@dataclass
class AgentTurn:
    response: str = ""
    events: list[dict] = field(default_factory=list)
    used_sql: list[str] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    error: str | None = None


def _fmt_table(columns: list[str], rows: list[list], n: int = _PREVIEW_ROWS) -> str:
    def cell(v) -> str:
        s = "" if v is None else str(v)
        return s if len(s) <= _CELL else s[: _CELL - 1] + "…"

    head = " | ".join(columns)
    body = "\n".join(" | ".join(cell(c) for c in r) for r in rows[:n])
    more = f"\n… ({len(rows) - n} more rows)" if len(rows) > n else ""
    return f"{head}\n{body}{more}"


class AnalystAgent:
    def __init__(
        self,
        root: str | Path,
        brain: Brain,
        *,
        sandbox_manager: SandboxManager | None = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self.root = Path(root)
        self.brain = brain
        self.sandboxes = sandbox_manager
        self.max_steps = max_steps
        self._qs: QueryService | None = None
        self._viz: VisualizationService | None = None

    # ---- data context ----------------------------------------------------

    def _context(self) -> str:
        with SchemaService.open(self.root) as svc:
            datasets = svc.list_datasets()
        if not datasets:
            return "No datasets have been uploaded yet."
        qs = self._query_service()
        lines = ["The user has these datasets (use the exact section/table/column names):"]
        for d in datasets:
            lines.append(f'\n• section "{d.name}"  (file: {d.source_filename})')
            for t in d.tables:
                cols = ", ".join(f"{c.name}" for c in t.columns)
                lines.append(f'    table "{t.name}" ({t.row_count} rows): {cols}')
            # a couple of sample rows from raw so the model "sees" the data
            try:
                sample = qs.run(f'SELECT * FROM "{d.name}"."raw"', page=1, page_size=3)
                if sample.rows:
                    lines.append("    sample of raw:")
                    lines.append("      " + _fmt_table(list(sample.columns), sample.rows, 3).replace("\n", "\n      "))
            except ServiceError:
                pass
        return "\n".join(lines)

    def _query_service(self) -> QueryService:
        if self._qs is None:
            self._qs = QueryService.open(self.root)
        return self._qs

    def _viz_service(self) -> VisualizationService:
        if self._viz is None:
            self._viz = VisualizationService.open(self.root)
        return self._viz

    def _close(self) -> None:
        if self._qs is not None:
            self._qs.close()
            self._qs = None
        if self._viz is not None:
            self._viz.close()
            self._viz = None

    # ---- tool execution --------------------------------------------------

    def _do_sql(self, sql: str) -> tuple[str, dict]:
        try:
            res = self._query_service().run(sql, page=1, page_size=200)
        except ServiceError as exc:
            return f"ERROR: {exc}", {"error": str(exc)}
        return _fmt_table(list(res.columns), res.rows), {"rows": len(res.rows)}

    def _do_chart(self, step: MakeChart) -> tuple[dict | None, str, dict | None]:
        req = ChartRequest(
            type=step.chart_type, section=step.section, table=step.table,
            x=step.x, y=step.y, color=step.color, row=step.row, col=step.col,
            value=step.value, aggregate=step.aggregate, bins=step.bins,
        )
        try:
            out = self._viz_service().visualize(req)
        except ServiceError as exc:
            return None, f"ERROR building chart: {exc}", None
        return (
            out.spec,
            f"created a {step.chart_type} chart with {out.row_count} points",
            req.model_dump(),
        )

    def _do_stat(self, step: RunStat) -> str:
        if self.sandboxes is None:
            return "ERROR: no sandbox available for statistics"
        handle = self.sandboxes.create()
        try:
            try:
                script = build_stat_script(
                    _stat_action(step)
                )
            except ValueError as exc:
                return f"ERROR: {exc}"
            run = run_script(handle, script)
            result = parse_stat_output(run.stdout)
            if not result.get("ok"):
                return f"ERROR: {result.get('error', 'test failed')}"
            return (
                f"{step.test}: statistic={result['statistic']:.4g}, "
                f"p={result['pvalue']:.4g} (n={result['n']})"
            )
        finally:
            self.sandboxes.delete(handle.id)

    # ---- the loop --------------------------------------------------------

    def run(self, message: str, history: list[dict] | None = None) -> Iterator[dict]:
        history = history or []
        try:
            self.brain.ensure_available()
        except OllamaUnavailableError as exc:
            yield {"type": "error", "error": str(exc)}
            return

        system = _TOOLS_DOC + "\n\n" + self._context()
        msgs: list[dict] = [{"role": m["role"], "content": m["content"]} for m in history]
        msgs.append({"role": "user", "content": message})

        try:
            for _ in range(self.max_steps):
                try:
                    decision = self.brain.decide_step(system, msgs)
                except AgentError:
                    break
                step = decision.step
                if isinstance(step, Answer):
                    break
                if isinstance(step, RunSql):
                    obs, meta = self._do_sql(step.sql)
                    summary = (
                        f"ERROR: {meta['error']}" if "error" in meta else f"{meta.get('rows', 0)} rows"
                    )
                    yield {
                        "type": "step", "tool": "run_sql", "thought": decision.thought,
                        "sql": step.sql, "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": f"run_sql: {step.sql}"})
                    msgs.append({"role": "user", "content": f"Observation:\n{obs}"})
                elif isinstance(step, MakeChart):
                    spec, summary, req = self._do_chart(step)
                    if spec is not None:
                        yield {"type": "chart", "spec": spec, "chart_request": req}
                    yield {
                        "type": "step", "tool": "make_chart", "thought": decision.thought,
                        "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": f"make_chart: {step.chart_type}"})
                    msgs.append({"role": "user", "content": f"Observation: {summary}"})
                elif isinstance(step, RunStat):
                    summary = self._do_stat(step)
                    yield {
                        "type": "step", "tool": "run_stat", "thought": decision.thought,
                        "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": f"run_stat: {step.test}"})
                    msgs.append({"role": "user", "content": f"Observation: {summary}"})

            # Answer phase — stream the grounded final answer.
            answer_msgs = msgs + [
                {"role": "user", "content": f"Now answer my question: {message}"}
            ]
            full: list[str] = []
            try:
                for tok in self.brain.stream_answer(_ANSWER_SYSTEM, answer_msgs):
                    full.append(tok)
                    yield {"type": "token", "text": tok}
            except OllamaUnavailableError as exc:
                yield {"type": "error", "error": str(exc)}
                return
            yield {"type": "final", "response": "".join(full).strip()}
        finally:
            self._close()

    def handle(self, message: str, history: list[dict] | None = None) -> AgentTurn:
        turn = AgentTurn()
        for ev in self.run(message, history):
            turn.events.append(ev)
            if ev["type"] == "error":
                turn.error = ev["error"]
            elif ev["type"] == "step" and ev["tool"] == "run_sql":
                turn.used_sql.append(ev["sql"])
            elif ev["type"] == "chart":
                turn.charts.append(ev)
            elif ev["type"] == "final":
                turn.response = ev["response"]
        return turn


def _stat_action(step: RunStat):
    # Adapt a RunStat step to the StatTestAction shape build_stat_script expects.
    from .actions import StatTestAction

    return StatTestAction(
        type="stat_test",
        test=step.test,
        section=step.section,
        table=step.table,
        columns=tuple(step.columns),
        group_by=step.group_by,
        sandbox_id="agent",
    )
