"""The analyst agent (Phase 5.1).

A chat agent with **read-only** access to the warehouse. Each turn: build schema
context, ask the brain for one action, validate it (already enforced by the
strict union), and execute it through the existing read-only services or a
sandbox. The agent always returns the natural-language response, the SQL or chart
spec it used, and the result. It NEVER writes to the canonical DB or any
non-sandbox resource — query/chart go through read-only services, stat tests run
in a sandbox, narrative touches nothing.
"""

from __future__ import annotations

from pathlib import Path

from executor import SandboxManager, run_script
from services import (
    ChartRequest,
    QueryService,
    SchemaService,
    ServiceError,
    VisualizationService,
)

from .actions import (
    AgentResponse,
    ChartAction,
    NarrativeAction,
    QueryAction,
    StatTestAction,
)
from .brain import AgentError, Brain
from .stats import build_stat_script, parse_stat_output

_SYSTEM = """\
You are Locus's data analyst. You help a scientist explore their datasets. You
have READ-ONLY access — you never modify data. Each turn you must choose exactly
ONE action and return it as JSON matching the schema:

- query: run a read-only SQL SELECT. Use the exact schema/table/column names
  below, fully qualified as "section"."table". SELECT only.
- chart: request a chart (chart_type one of histogram/bar/heatmap/dose_response/
  scatter) by naming section, table, and the relevant columns. The server
  aggregates and builds the spec.
- stat_test: run a named test (ttest_ind/ttest_rel/mannwhitneyu/pearsonr/
  spearmanr/f_oneway) on a section/table's columns inside a sandbox.
- narrative: answer in plain language with no data access.

Prefer querying the verbatim "raw" table unless a fact/dimension table is clearly
better. Only reference columns that exist.
"""


class AnalystAgent:
    def __init__(
        self, root: str | Path, brain: Brain, *, sandbox_manager: SandboxManager | None = None
    ) -> None:
        self.root = Path(root)
        self.brain = brain
        self.sandboxes = sandbox_manager

    # ---- schema context --------------------------------------------------

    def _schema_context(self) -> str:
        with SchemaService.open(self.root) as svc:
            datasets = svc.list_datasets()
        if not datasets:
            return "No datasets have been uploaded yet."
        lines = ["Available datasets (section -> tables -> columns):"]
        for d in datasets:
            lines.append(f"- section {d.name!r} (from {d.source_filename}):")
            for t in d.tables:
                cols = ", ".join(c.name for c in t.columns)
                lines.append(f"    {t.name} ({t.row_count} rows): {cols}")
        return "\n".join(lines)

    def _build_user_prompt(self, message: str, history: list[dict]) -> str:
        parts = []
        for turn in history[-10:]:
            role = turn.get("role", "user")
            parts.append(f"{role}: {turn.get('content', '')}")
        parts.append(f"user: {message}")
        return "\n".join(parts)

    # ---- main turn -------------------------------------------------------

    def handle(self, message: str, history: list[dict] | None = None) -> AgentResponse:
        history = history or []
        system = _SYSTEM + "\n\n" + self._schema_context()
        user = self._build_user_prompt(message, history)

        try:
            decision = self.brain.decide(system, user)
        except AgentError as exc:
            return AgentResponse(
                response="I couldn't form a valid action for that. Could you rephrase?",
                action_type="narrative",
                error=str(exc),
            )

        action = decision.action
        narration = decision.narration

        if isinstance(action, QueryAction):
            return self._do_query(action, narration)
        if isinstance(action, ChartAction):
            return self._do_chart(action, narration)
        if isinstance(action, StatTestAction):
            return self._do_stat_test(action, narration)
        assert isinstance(action, NarrativeAction)
        return AgentResponse(
            response=action.text or narration or "", action_type="narrative"
        )

    # ---- executors (all read-only / sandboxed) --------------------------

    def _do_query(self, action: QueryAction, narration: str) -> AgentResponse:
        try:
            with QueryService.open(self.root) as q:
                res = q.run(action.sql)
        except ServiceError as exc:
            return AgentResponse(
                response=f"That query couldn't run: {exc}",
                action_type="query",
                sql=action.sql,
                error=str(exc),
            )
        return AgentResponse(
            response=narration or f"Ran the query; {len(res.rows)} row(s) returned.",
            action_type="query",
            sql=action.sql,
            result={
                "columns": list(res.columns),
                "rows": res.rows,
                "has_more": res.has_more,
                "execution_ms": res.execution_ms,
            },
        )

    def _do_chart(self, action: ChartAction, narration: str) -> AgentResponse:
        req = ChartRequest(
            type=action.chart_type,
            section=action.section,
            table=action.table,
            x=action.x,
            y=action.y,
            color=action.color,
            row=action.row,
            col=action.col,
            value=action.value,
            aggregate=action.aggregate,
            bins=action.bins,
        )
        try:
            with VisualizationService.open(self.root) as viz:
                out = viz.visualize(req)
        except ServiceError as exc:
            return AgentResponse(
                response=f"I couldn't build that chart: {exc}",
                action_type="chart",
                error=str(exc),
            )
        return AgentResponse(
            response=narration or f"Built a {action.chart_type} chart.",
            action_type="chart",
            spec=out.spec,
            result={"data": out.data, "row_count": out.row_count, "truncated": out.truncated},
        )

    def _do_stat_test(self, action: StatTestAction, narration: str) -> AgentResponse:
        if self.sandboxes is None:
            return AgentResponse(
                response="No sandbox is available to run a statistical test.",
                action_type="stat_test",
                error="no sandbox manager",
            )
        handle = self.sandboxes.get(action.sandbox_id)
        if handle is None:
            return AgentResponse(
                response=f"Sandbox {action.sandbox_id!r} does not exist. Create one first.",
                action_type="stat_test",
                error="unknown sandbox",
            )
        try:
            script = build_stat_script(action)
        except ValueError as exc:
            return AgentResponse(
                response=f"That test can't be set up: {exc}",
                action_type="stat_test",
                error=str(exc),
            )
        run = run_script(handle, script)
        result = parse_stat_output(run.stdout)
        if not result.get("ok"):
            return AgentResponse(
                response=f"The {action.test} test failed: {result.get('error', 'unknown error')}",
                action_type="stat_test",
                error=result.get("error"),
                result=result,
            )
        return AgentResponse(
            response=(
                narration
                or f"{action.test}: statistic={result['statistic']:.4g}, "
                f"p={result['pvalue']:.4g} (n={result['n']})."
            ),
            action_type="stat_test",
            result=result,
        )
