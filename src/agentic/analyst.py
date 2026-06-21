"""The analyst agent — a multi-step, tool-using LLM over your data.

Each turn the agent runs a short ReAct loop on a local Ollama model: it inspects
a rich description of the datasets, issues validated read-only tools (SQL,
charts, statistics), observes the results, iterates, and finally writes a fluent,
streamed natural-language answer grounded in what it actually found.

Security: exploration tools are validated and executed through the read-only
services (SELECT-only queries, server-aggregated charts) or a disposable sandbox
(statistics) — the model never touches data directly. The model can also *propose*
data changes (edit/delete/restructure), but it can NEVER execute them: a proposed
change is shown to the user for explicit confirmation and applied deterministically
by the API layer only if they approve. The loop here has no write path at all.

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

from . import schema_card
from .brain import AgentError, Brain
from .mutation import MutationAction
from .stats import build_stat_script, parse_stat_output
from .steps import (
    Answer,
    AskUser,
    CheckData,
    Define,
    DeleteData,
    EditData,
    MakeChart,
    MakeFigure,
    PlotSpec,
    Restructure,
    RunSql,
    RunStat,
)

_PROCEED_WORDS = ("proceed", "exclude", "continue", "go ahead", "drop ", "ignore missing", "yes")

# A mutation is only ever proposed when the user's own message asks for a change.
# This is a backstop in front of the (mandatory) human confirmation gate, so the
# agent never even proposes editing data the user didn't ask to change.
_MUTATE_INTENT = (
    "delete", "remove", "drop ", "edit", "change", "update", "set ", "modify",
    "rename", "fix", "replace", "overwrite", "clear", "wipe", "correct",
    "add column", "add a column", "new column", "restructure", "rename column",
)

MAX_STEPS = 8
_PREVIEW_ROWS = 12
_CELL = 60
_MAX_PLOT_ROWS = 5000  # cap rows injected into a custom (plot) Vega spec

_TOOLS_DOC = """\
You are Locus's data analyst, helping a scientist explore their datasets and
write up findings. Explore the data YOURSELF with tools before answering. By
default you only READ the data. You may also PROPOSE changes to the data (edit,
delete, restructure) — but ONLY when the user explicitly asks you to change it,
and every proposed change must be confirmed by the user before anything happens.

You are GROUNDED by the schema card below: it states each table's purpose, every
column's type/meaning/units with real example values, the relationships, curated
metric definitions, and known gotchas. Trust it — never invent a column, value, or
metric that is not in the card. If the user defines a term or metric, record it
with the `define` step so it persists in the card.

CRITICAL — every column is stored as TEXT (VARCHAR). For ANY numeric work
(AVG, SUM, MIN, MAX, comparisons, math) you MUST cast: TRY_CAST("col" AS DOUBLE).
e.g. SELECT AVG(TRY_CAST("age" AS DOUBLE)) FROM "section"."raw".
The schema card marks which columns are numeric.

Each turn, respond with JSON: {"thought":"...", "step":{...}}. Choose ONE step:

- run_sql:    {"kind":"run_sql","sql":"SELECT ..."}
    A single read-only SELECT. Use fully-qualified "section"."table" and the
    EXACT column names from the profile. Quote identifiers with DOUBLE QUOTES
    ("cohort"), never backticks. Use single quotes for text literals ('yes').
    To count rows use COUNT(*), not COUNT(DISTINCT ...). Prefer the "raw" table.
    Useful idioms (all columns are TEXT):
      • average of a numeric column:  AVG(TRY_CAST("age" AS DOUBLE))
      • rate/proportion of a category: AVG(CASE WHEN "responder"='yes' THEN 1.0 ELSE 0 END)
        (or COUNT(*) FILTER (WHERE "responder"='yes') * 1.0 / COUNT(*))
      • a percentage is that × 100. Group with GROUP BY for per-category results.
- plot:       {"kind":"plot","sql":"SELECT ... FROM data","spec":{...vega-lite...},"title":"..."}
    *** The PRIMARY way to make a visualization. *** Build EXACTLY the chart the
    user asked for — any kind (scatter, line, box/violin, grouped/stacked bar,
    area, faceted, multi-series, binned, etc.) — for THIS dataset. Two parts:
      1) "sql": a read-only SELECT whose FROM clause is the virtual table named
         `data` (it already refers to the current dataset's table — do NOT write a
         schema or section name, just `FROM data`). Return the columns you want to
         plot, cast numeric columns with TRY_CAST, and give readable aliases.
         Aggregate/GROUP BY or LIMIT so you return a sensible number of rows.
      2) "spec": a Vega-Lite v5 spec. Reference your SELECT's OUTPUT column aliases
         in the encoding. Do NOT include the data — the query rows are injected
         automatically. Set the encoding "type" correctly (quantitative for numbers,
         nominal/ordinal for categories, temporal for dates).
    Example — average inhibition per gene, sorted, as a bar chart:
      {"kind":"plot",
       "sql":"SELECT \"target_gene\" AS gene, AVG(TRY_CAST(\"pct_inhibition\" AS DOUBLE)) AS avg_inhibition FROM data GROUP BY 1 ORDER BY 2 DESC",
       "spec":{"mark":"bar","encoding":{"x":{"field":"gene","type":"nominal","sort":"-y"},"y":{"field":"avg_inhibition","type":"quantitative"}}},
       "title":"Average % inhibition by gene"}
    Example — logP vs molecular weight, colored by gene (a scatter):
      {"kind":"plot",
       "sql":"SELECT TRY_CAST(\"logp\" AS DOUBLE) AS logp, TRY_CAST(\"mol_weight\" AS DOUBLE) AS mw, \"target_gene\" AS gene FROM data",
       "spec":{"mark":"point","encoding":{"x":{"field":"logp","type":"quantitative"},"y":{"field":"mw","type":"quantitative"},"color":{"field":"gene","type":"nominal"}}}}
    If a plot returns an ERROR, read it, fix the SQL or spec, and try plot again.
- make_chart: {"kind":"make_chart","chart_type":"histogram|bar|heatmap|dose_response|scatter",
               "section":"...","table":"raw","x":"col","y":"col","color":"col",...}
    OPTIONAL shortcut for a few standard charts of existing columns (the server
    aggregates/casts for you). Prefer "plot" whenever the user wants a specific
    chart — make_chart only covers these fixed types.
- make_figure:{"kind":"make_figure","code":"...python...","caption":"..."}
    A custom matplotlib figure for a report. In the sandbox, `con`, `pd`, `np`,
    and `plt` are ALREADY defined — do NOT import anything, do NOT call
    duckdb.connect, do NOT create views. `con` is already connected to the data.
    Query with con.execute('SELECT ... FROM "<section>"."raw"').df() using the
    EXACT section name from the profile, then draw with plt. The figure is saved
    automatically (no plt.show needed). Cast numerics with TRY_CAST. Example
    (replace the section name with the real one):
      df = con.execute('SELECT "cohort", COUNT(*) AS n FROM "abc__123"."raw" GROUP BY "cohort"').df()
      plt.figure(figsize=(7,4)); plt.bar(df["cohort"], df["n"]); plt.title("Patients per cohort"); plt.ylabel("count")
    Use for regressions, error bars, multi-panel or annotated report figures.
- run_stat:   {"kind":"run_stat","test":"ttest_ind|ttest_rel|mannwhitneyu|pearsonr|spearmanr|f_oneway",
               "section":"...","table":"raw","columns":["a","b"],"group_by":"col"}
    A statistical test in a sandbox.
- check_data: {"kind":"check_data","section":"...","table":"raw","columns":["a","b"]}
    Inspect columns for missing values / non-numeric entries before using them.
- define:     {"kind":"define","section":"...","target":"metric|column|dataset",
               "name":"...","meaning":"...","units":"...","sql":"..."}
    Save a definition into the schema card so it persists. Use when the user states
    what a term means or you establish a reusable metric — e.g. target "metric",
    name "responder_rate", meaning "share of patients with responder='yes'",
    sql "AVG(CASE WHEN \"responder\"='yes' THEN 1.0 ELSE 0 END)". After defining,
    continue answering.
- ask_user:   {"kind":"ask_user","question":"...","options":["...","..."]}
    PAUSE and ask the human, offering 2-4 short clickable options. This ends your
    turn until they choose.
- answer:     {"kind":"answer"}   Stop exploring and write the final answer.

Changing data — ONLY when the user explicitly asks (e.g. "delete the rows where…",
"set bmi to 0 for…", "rename the column…", "drop the column…"). These steps do NOT
change anything by themselves: they PROPOSE a change that the user must confirm
with a button click. Never propose a change the user didn't ask for; if they only
asked a question, just answer it.
- edit_data:  {"kind":"edit_data","section":"...","table":"raw","set_column":"col",
               "set_value":"...","where":"\"cohort\" = 'control'"}
    Change a column's value for matching rows (omit "where" to change all rows).
- delete_data:{"kind":"delete_data","section":"...","table":"raw",
               "where":"TRY_CAST(\"age\" AS DOUBLE) > 90"}
    Delete matching rows ("where" is a boolean SQL expression; quote identifiers
    with double quotes and text with single quotes).
- restructure_data:{"kind":"restructure_data","operation":"add_column|drop_column|rename_column",
               "section":"...","column":"col","new_name":"..."}
    Add, drop, or rename a column (new_name only for rename_column).
After proposing one change step, STOP — do not also answer; the confirmation
prompt is shown to the user automatically.

Human-in-the-loop — real lab data has errors; never silently skip them:
- The profile flags columns with nulls. If the user asks to chart/analyze a column
  that has missing or non-numeric values, do NOT just drop them. First use
  ask_user to ask how to handle it, with concrete options like
  ["Exclude the rows with missing values and continue", "Show me those rows first",
  "Cancel"]. Only build the chart after they choose; then set
  "confirm_incomplete": true on make_chart.
- Use check_data when unsure whether a column is clean.
- If a column/category/filter is NOT in the profile, do not substitute another —
  use ask_user or answer that it isn't in the data.
- Only ask_user when you genuinely need the human's decision (a real data problem
  or a true ambiguity). For straightforward questions, just answer — don't ask
  unnecessary clarifying questions.

Workflow: when the user asks for a chart/plot/graph/visualization, use "plot" to
build exactly what they asked for from this dataset (you may run_sql first to check
column names/values). For questions about numbers, get REAL numbers (verify with
COUNT/GROUP BY) and handle data issues with the human. Make at most ONE chart, then
answer briefly.

Patterns to imitate (adapt the column/section names to the schema card above):
  Q: "How many rows in each cohort?"
  → run_sql: SELECT "cohort", COUNT(*) AS n FROM "sec"."raw" GROUP BY 1 ORDER BY 2 DESC
  Q: "What's the average age of responders vs non-responders?"
  → run_sql: SELECT "responder", AVG(TRY_CAST("age" AS DOUBLE)) AS avg_age
             FROM "sec"."raw" GROUP BY 1
  Q: "What fraction responded?"
  → run_sql: SELECT AVG(CASE WHEN "responder"='yes' THEN 1.0 ELSE 0 END) AS rate
             FROM "sec"."raw"
"""

_ANSWER_SYSTEM = """\
You are Locus's data analyst. Answer the user's latest question using ONLY the
numbers in the observations above (query results, statistics).

CRITICAL: Never invent or guess numbers. If the observations are empty, only
contain errors, or do not actually contain the figure asked for, say plainly that
you could not compute it and suggest how to rephrase — do NOT make up values.

If a chart or figure was created successfully (the observation says it is shown to
the user), present it positively — e.g. "Here is a bar chart of …" — and describe
what it shows. Do not say you couldn't make it.

Output ONLY the final answer — do NOT narrate your reasoning, do NOT restate the
question, do NOT write "Okay" or "Let me". No <think> blocks.

Format in clean Markdown:
- Lead with the answer; **bold** the key numbers.
- Use a short bullet list for breakdowns; a Markdown table for 2+ columns of data.
- Keep it tight (a few sentences/bullets). If you made a chart, mention it in one line.
- Never invent numbers you did not observe.
"""


@dataclass
class AgentTurn:
    response: str = ""
    events: list[dict] = field(default_factory=list)
    used_sql: list[str] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)
    asks: list[dict] = field(default_factory=list)
    confirms: list[dict] = field(default_factory=list)
    error: str | None = None


import re

_CAST_RE = re.compile(r"(?:try_)?cast\(\s*(.+?)\s+as\s+\w+\s*\)", re.IGNORECASE)


def _clean_col(name: str | None) -> str | None:
    """Normalize a chart column field: models sometimes pass SQL expressions like
    TRY_CAST("x" AS DOUBLE) or quoted/backticked names. Chart fields must be plain
    column names (the visualization service casts internally)."""
    if not name:
        return name
    s = name.strip()
    m = _CAST_RE.fullmatch(s)
    if m:
        s = m.group(1).strip()
    return s.strip().strip('`"').strip() or None


def _clean_code(code: str) -> str:
    """Strip wrappers a model sometimes adds (```python fences, <python> tags),
    then normalize MySQL backtick quoting in any embedded SQL."""
    c = code.strip()
    if c.startswith("<python>"):
        c = c[len("<python>") :]
    if c.endswith("</python>"):
        c = c[: -len("</python>")]
    c = c.strip()
    if c.startswith("```"):
        c = c.split("\n", 1)[1] if "\n" in c else c[3:]
        if c.rstrip().endswith("```"):
            c = c.rstrip()[:-3]
    return c.strip().replace("`", '"')


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

    def _context(self, section: str | None = None) -> str:
        with SchemaService.open(self.root) as svc:
            datasets = svc.list_datasets()
        if not datasets:
            return "No datasets have been uploaded yet."
        # Schema linking: scope to the dataset the user is working in. For anything
        # beyond it, the model gets a compact index, not every column of every table.
        if section is not None:
            scoped = [d for d in datasets if d.name == section]
            if scoped:
                datasets = scoped
        qs = self._query_service()
        cards = [
            schema_card.build_card(qs, d, schema_card.load_curation(self.root, d.name))
            for d in datasets
        ]
        if len(cards) == 1:
            lead = (
                "Here is the schema card for the ONE dataset you are working in. Use this "
                "section in every tool; never invent a column or value not listed here."
            )
            return lead + "\n\n" + schema_card.render_card(cards[0])
        lead = (
            "Here are the user's datasets. Pick the ONE relevant to the question and use "
            "its EXACT section/column names; never invent a column or value."
        )
        return lead + "\n\n" + schema_card.render_index(cards)

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

    def _column_issues(self, section: str, table: str, columns: list[str]) -> dict[str, dict]:
        """Deterministic data-quality findings per column: missing (null) and
        non-numeric counts. The grounding for human-in-the-loop questions."""

        def q(c: str) -> str:
            return '"' + c.replace('"', '""') + '"'

        cols = [c for c in columns if c]
        if not cols:
            return {}
        raw = f'"{section}"."{table}"'
        parts = ["COUNT(*) AS n"]
        for i, c in enumerate(cols):
            parts.append(f"COUNT(*) FILTER (WHERE {q(c)} IS NULL) AS miss{i}")
            parts.append(f"COUNT(*) FILTER (WHERE {q(c)} IS NOT NULL AND TRY_CAST({q(c)} AS DOUBLE) IS NULL) AS nonnum{i}")
        try:
            res = self._query_service().run(f"SELECT {', '.join(parts)} FROM {raw}", page_size=1)
            row = dict(zip(res.columns, res.rows[0]))
        except ServiceError:
            return {}
        out: dict[str, dict] = {}
        for i, c in enumerate(cols):
            out[c] = {
                "n": int(row.get("n") or 0),
                "missing": int(row.get(f"miss{i}") or 0),
                "nonnumeric": int(row.get(f"nonnum{i}") or 0),
            }
        return out

    def _chart_columns(self, step: MakeChart) -> list[str]:
        return [c for c in (step.x, step.y, step.color, step.row, step.col, step.value) if c]

    def _numeric_roles(self, step: MakeChart) -> set[str]:
        """Columns this chart needs to be numeric (non-numeric there is a problem;
        elsewhere, e.g. a bar's categorical x, it's expected)."""
        t = step.chart_type
        cols: set[str | None] = set()
        if t == "histogram":
            cols = {step.x}
        elif t == "bar":
            cols = {step.y} if step.aggregate != "count" else set()
        elif t == "heatmap":
            cols = {step.value}
        elif t in ("dose_response", "scatter"):
            cols = {step.x, step.y}
        return {c for c in cols if c}

    def _do_sql(self, sql: str) -> tuple[str, dict]:
        # Models often emit MySQL-style backtick quoting; DuckDB has no use for
        # backticks, so normalizing them to double quotes is safe and fixes a
        # very common failure.
        sql = sql.replace("`", '"')
        try:
            res = self._query_service().run(sql, page=1, page_size=200)
        except ServiceError as exc:
            return f"ERROR: {exc}", {"error": str(exc)}
        if not res.rows:
            return "(0 rows returned)", {"rows": 0}
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

    def _do_plot(self, step: PlotSpec, section: str | None = None) -> tuple[dict | None, str]:
        """Run the model's SELECT and inject the rows into its Vega-Lite spec, so
        the agent can build ANY chart it wants from real data — not a template.

        The model writes its query against a virtual table ``data`` (we bind it to
        the real ``"section"."table"`` here), which removes the error-prone job of
        fully-qualifying the schema from the model."""
        eff_section = section or step.section
        if not eff_section:
            return None, "ERROR: no dataset selected for the plot."
        table = step.table or "raw"
        user_sql = step.sql.replace("`", '"')
        real = f'"{eff_section}"."{table}"'
        # Bind `data` to the real table; if the model already qualified the table
        # itself, the CTE is simply unused and its own FROM still works.
        sql = f"WITH data AS (SELECT * FROM {real}) {user_sql}"
        try:
            res = self._query_service().run(sql, page=1, page_size=_MAX_PLOT_ROWS)
        except ServiceError as exc:
            return None, f"ERROR running the query: {exc}"
        if not res.rows:
            return None, (
                "ERROR: the query returned 0 rows. Check the column names, your "
                "filters, and that numeric columns are wrapped in TRY_CAST."
            )
        spec = step.spec
        if not isinstance(spec, dict) or not spec:
            return None, "ERROR: 'spec' must be a Vega-Lite object."
        if not any(
            k in spec for k in ("mark", "layer", "facet", "hconcat", "vconcat", "concat", "repeat")
        ):
            return None, "ERROR: the Vega-Lite spec needs a 'mark' (or layer/facet/concat)."
        # Inject the real data; the model uses a "table"/named placeholder.
        spec = dict(spec)
        spec["data"] = {"values": [dict(zip(res.columns, r)) for r in res.rows]}
        spec.setdefault("$schema", "https://vega.github.io/schema/vega-lite/v5.json")
        if step.title and "title" not in spec:
            spec["title"] = step.title
        spec.setdefault("width", "container")
        spec.setdefault("height", 260)
        return spec, f"created a custom chart with {len(res.rows)} rows"

    def _do_figure(self, step: MakeFigure) -> tuple[str | None, str]:
        """Run the model's matplotlib code in a sandbox and return the figure as
        a base64 data URI (so it renders inline, no artifact serving needed)."""
        if self.sandboxes is None:
            return None, "ERROR: no sandbox available for figures"
        handle = self.sandboxes.create()
        try:
            run = run_script(handle, _clean_code(step.code))
            pngs = [a for a in run.artifacts if a.lower().endswith(".png")]
            if not pngs:
                detail = run.stderr.strip()[-400:] if run.stderr.strip() else "no figure was drawn"
                return None, f"ERROR: {detail}"
            import base64

            data = (handle.outputs_dir / run.run_id / pngs[0]).read_bytes()
            return "data:image/png;base64," + base64.b64encode(data).decode(), "figure created"
        finally:
            self.sandboxes.delete(handle.id)

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

    # ---- mutations (propose only; never executed here) -------------------

    def _mutation_action(self, step) -> MutationAction:
        """Translate a proposed mutation tool step into a structured action."""
        if isinstance(step, EditData):
            return MutationAction(
                op="update", section=step.section, table=step.table,
                set_column=step.set_column, set_value=step.set_value, where=step.where,
            )
        if isinstance(step, DeleteData):
            return MutationAction(
                op="delete", section=step.section, table=step.table, where=step.where
            )
        # Restructure
        return MutationAction(
            op=step.operation, section=step.section, table=step.table,
            column=step.column, new_name=step.new_name,
        )

    def _confirm_event(self, action: MutationAction) -> dict:
        """Build the confirmation prompt for a proposed change. For row-scoped
        edits/deletes we count the affected rows first so the user sees the blast
        radius before approving."""
        affected: int | None = None
        if action.is_row_scoped():
            where = "" if not action.where else f" WHERE {action.where.replace('`', chr(34))}"
            try:
                res = self._query_service().run(
                    f'SELECT COUNT(*) AS n FROM "{action.section}"."{action.table}"{where}',
                    page_size=1,
                )
                affected = int(res.rows[0][0]) if res.rows else 0
            except ServiceError:
                affected = None
        verb = "Delete" if action.op == "delete" else "Apply change"
        return {
            "type": "confirm",
            "summary": action.describe(affected),
            "detail": action.preview_sql(),
            "note": "Your original uploaded file stays intact and recoverable.",
            "affected": affected,
            "action": action.model_dump(),
            "options": [
                (f"{verb}" if affected is None else f"{verb} ({affected} rows)")
                if action.is_row_scoped()
                else "Confirm this change",
                "Cancel",
            ],
        }

    # ---- the loop --------------------------------------------------------

    def run(
        self, message: str, history: list[dict] | None = None, section: str | None = None
    ) -> Iterator[dict]:
        history = history or []
        try:
            self.brain.ensure_available()
        except OllamaUnavailableError as exc:
            yield {"type": "error", "error": str(exc)}
            return

        system = _TOOLS_DOC + "\n\n" + self._context(section)
        msgs: list[dict] = [{"role": m["role"], "content": m["content"]} for m in history]
        msgs.append({"role": "user", "content": message})
        self._message = message

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
                    # Normalize column fields (strip stray TRY_CAST(...)/quotes the
                    # model sometimes adds) before the gate and the build.
                    step = step.model_copy(
                        update={
                            r: _clean_col(getattr(step, r))
                            for r in ("x", "y", "color", "row", "col", "value")
                        }
                    )
                    # Human-in-the-loop gate: if the plotted columns have missing /
                    # non-numeric values and the user hasn't agreed to proceed, ask
                    # them how to handle it instead of silently dropping rows.
                    proceed = step.confirm_incomplete or any(
                        w in self._message.lower() for w in _PROCEED_WORDS
                    )
                    numeric = self._numeric_roles(step)
                    bad = {
                        c: v
                        for c, v in self._column_issues(
                            step.section, step.table, self._chart_columns(step)
                        ).items()
                        if v["missing"] or (c in numeric and v["nonnumeric"])
                    }
                    if bad and not proceed:
                        descs = []
                        for c, v in bad.items():
                            bits = []
                            if v["missing"]:
                                bits.append(f"{v['missing']} missing")
                            if c in numeric and v["nonnumeric"]:
                                bits.append(f"{v['nonnumeric']} non-numeric")
                            descs.append(f'"{c}" ({", ".join(bits)} of {v["n"]} rows)')
                        yield {
                            "type": "ask",
                            "question": "Some values needed for this chart are missing or invalid: "
                            + "; ".join(descs)
                            + ". How should I handle them?",
                            "options": [
                                "Exclude those rows and continue",
                                "Show me the affected rows first",
                                "Cancel",
                            ],
                        }
                        return
                    spec, summary, req = self._do_chart(step)
                    if spec is not None:
                        yield {"type": "chart", "spec": spec, "chart_request": req}
                        obs = f"{summary}. The chart is now shown to the user. Use the 'answer' step next and describe it briefly."
                    else:
                        obs = summary
                    yield {
                        "type": "step", "tool": "make_chart", "thought": decision.thought,
                        "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": f"make_chart: {step.chart_type}"})
                    msgs.append({"role": "user", "content": f"Observation: {obs}"})
                elif isinstance(step, PlotSpec):
                    spec, summary = self._do_plot(step, section)
                    if spec is not None:
                        yield {"type": "chart", "spec": spec, "chart_request": None}
                        obs = (
                            f"{summary}. The chart is now shown to the user. Use the "
                            "'answer' step next and describe what it shows briefly."
                        )
                    else:
                        obs = summary  # an ERROR string — the model can fix and retry
                    yield {
                        "type": "step", "tool": "plot", "thought": decision.thought,
                        "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": f"plot: {step.sql}"})
                    msgs.append({"role": "user", "content": f"Observation: {obs}"})
                elif isinstance(step, CheckData):
                    issues = self._column_issues(step.section, step.table, step.columns)
                    if issues:
                        obs = "; ".join(
                            f'"{c}": {v["missing"]} missing, {v["nonnumeric"]} non-numeric (of {v["n"]})'
                            for c, v in issues.items()
                        )
                    else:
                        obs = "no columns checked"
                    yield {
                        "type": "step", "tool": "check_data", "thought": decision.thought,
                        "summary": obs,
                    }
                    msgs.append({"role": "assistant", "content": "check_data"})
                    msgs.append({"role": "user", "content": f"Data check: {obs}"})
                elif isinstance(step, Define):
                    sec = step.section or section or ""
                    if not sec:
                        obs = "ERROR: no dataset to define against."
                    else:
                        obs = schema_card.define(
                            self.root, sec, target=step.target, name=step.name,
                            meaning=step.meaning, units=step.units, sql=step.sql,
                        )
                    yield {
                        "type": "step", "tool": "define", "thought": decision.thought,
                        "summary": obs,
                    }
                    msgs.append({"role": "assistant", "content": "define"})
                    msgs.append({"role": "user", "content": f"Observation: {obs}"})
                elif isinstance(step, AskUser):
                    opts = [o for o in step.options if o.strip()] or ["Yes", "No"]
                    yield {"type": "ask", "question": step.question, "options": opts}
                    return
                elif isinstance(step, RunStat):
                    summary = self._do_stat(step)
                    yield {
                        "type": "step", "tool": "run_stat", "thought": decision.thought,
                        "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": f"run_stat: {step.test}"})
                    msgs.append({"role": "user", "content": f"Observation: {summary}"})
                elif isinstance(step, MakeFigure):
                    image, summary = self._do_figure(step)
                    if image is not None:
                        yield {"type": "figure", "image": image, "caption": step.caption}
                        obs = (
                            "The figure was created successfully and is now shown to the user. "
                            "Use the 'answer' step next. Describe what the figure shows "
                            "qualitatively; do NOT state specific counts or values unless you "
                            "obtained them from a run_sql result."
                        )
                    else:
                        obs = summary
                    yield {
                        "type": "step", "tool": "make_figure", "thought": decision.thought,
                        "summary": summary,
                    }
                    msgs.append({"role": "assistant", "content": "make_figure"})
                    msgs.append({"role": "user", "content": f"Observation: {obs}"})
                elif isinstance(step, (EditData, DeleteData, Restructure)):
                    # Backstop: only ever PROPOSE a change the user explicitly asked
                    # for. If their message has no change-intent, refuse to mutate
                    # and steer the model back to answering read-only.
                    if not any(w in self._message.lower() for w in _MUTATE_INTENT):
                        obs = (
                            "Refused: the user did not ask to change the data, so data "
                            "changes are not allowed. Answer their question using read-only "
                            "tools instead."
                        )
                        yield {
                            "type": "step", "tool": "blocked_mutation",
                            "thought": decision.thought, "summary": obs,
                        }
                        msgs.append({"role": "assistant", "content": "(attempted a data change)"})
                        msgs.append({"role": "user", "content": obs})
                        continue
                    action = self._mutation_action(step)
                    yield {
                        "type": "step", "tool": "propose_change",
                        "thought": decision.thought, "summary": action.describe(),
                    }
                    # Propose only — the change is NOT executed here. It is shown to
                    # the user for confirmation and applied by the API layer only if
                    # they approve. End the turn awaiting their decision.
                    yield self._confirm_event(action)
                    return

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

    def handle(
        self, message: str, history: list[dict] | None = None, section: str | None = None
    ) -> AgentTurn:
        turn = AgentTurn()
        for ev in self.run(message, history, section):
            turn.events.append(ev)
            if ev["type"] == "error":
                turn.error = ev["error"]
            elif ev["type"] == "step" and ev["tool"] == "run_sql":
                turn.used_sql.append(ev["sql"])
            elif ev["type"] == "chart":
                turn.charts.append(ev)
            elif ev["type"] == "figure":
                turn.figures.append(ev)
            elif ev["type"] == "ask":
                turn.asks.append(ev)
            elif ev["type"] == "confirm":
                turn.confirms.append(ev)
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
