"""The analyst's tool steps (multi-step agent).

Each turn the model proposes ONE step as strict JSON. The loop validates it
against this union (the model never executes anything) and runs it through the
read-only services or a sandbox. After gathering observations, the model writes
a free-form, streamed answer. Four steps:

  * run_sql    — explore the data with a read-only SELECT
  * make_chart — build a server-aggregated chart
  * run_stat   — run a named statistical test in a sandbox
  * answer     — stop gathering; write the final answer
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

StatTest = Literal[
    "ttest_ind", "ttest_rel", "mannwhitneyu", "pearsonr", "spearmanr", "f_oneway"
]
ChartType = Literal["histogram", "bar", "heatmap", "dose_response", "scatter"]
Aggregate = Literal["count", "sum", "avg", "min", "max"]


class _Step(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RunSql(_Step):
    kind: Literal["run_sql"]
    sql: str = Field(description="A single read-only SELECT.")


class MakeChart(_Step):
    kind: Literal["make_chart"]
    chart_type: ChartType
    section: str
    table: str = "raw"
    x: str | None = None
    y: str | None = None
    color: str | None = None
    row: str | None = None
    col: str | None = None
    value: str | None = None
    aggregate: Aggregate = "count"
    bins: int = 30
    # Set true only after the user has agreed to proceed despite missing/invalid
    # values in the plotted columns (see the human-in-the-loop data check).
    confirm_incomplete: bool = False


class RunStat(_Step):
    kind: Literal["run_stat"]
    test: StatTest
    section: str
    table: str = "raw"
    columns: list[str] = Field(default_factory=list)
    group_by: str | None = None


class MakeFigure(_Step):
    """Generate a publication-style figure with matplotlib in a sandbox.

    ``code`` is Python that has ``con`` (a DuckDB connection to the data), ``pd``,
    ``np``, and ``plt`` available; any figure it draws is captured automatically.
    Used for research-report figures (regressions, error bars, annotations) that
    go beyond the quick built-in chart types.
    """

    kind: Literal["make_figure"]
    code: str
    caption: str = ""


class CheckData(_Step):
    """Inspect columns for data-quality problems (missing values, non-numeric
    entries, distinct counts) — grounded, deterministic findings to reason over
    before analyzing or charting."""

    kind: Literal["check_data"]
    section: str
    table: str = "raw"
    columns: list[str] = Field(default_factory=list)


class AskUser(_Step):
    """Pause and ask the human a question with clickable options. Use this when a
    decision is genuinely the user's to make — especially how to handle data
    problems (e.g. rows with missing values) before proceeding."""

    kind: Literal["ask_user"]
    question: str
    options: list[str] = Field(default_factory=list, min_length=1, max_length=4)


class Answer(_Step):
    kind: Literal["answer"]


AgentStep = Annotated[
    Union[RunSql, MakeChart, RunStat, MakeFigure, CheckData, AskUser, Answer],
    Field(discriminator="kind"),
]


class StepDecision(BaseModel):
    """What the model returns each loop iteration."""

    model_config = ConfigDict(extra="ignore")

    thought: str = Field(default="", description="One short sentence of reasoning.")
    step: AgentStep
