"""The analyst's tool steps (multi-step agent).

Each turn the model proposes ONE step as strict JSON. The loop validates it
against this union (the model never executes anything) and runs it through the
read-only services or a sandbox. After gathering observations, the model writes
a free-form, streamed answer.

Read-only exploration steps: run_sql, make_chart, make_figure, run_stat,
check_data; plus ask_user (pause for a human decision) and answer (finish).

Mutation steps — edit_data, delete_data, restructure_data — only *propose* a
change. They are never executed by the loop: the change is shown to the user for
explicit confirmation and applied deterministically by the API layer only if they
approve. The agent must propose these only when the user explicitly asks to
change the data.
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


class EditData(_Step):
    """Propose a value edit to the data (an UPDATE). Use ONLY when the user
    explicitly asks to change/edit/fix/set values. Nothing happens until the user
    confirms — this step just proposes the change for their approval."""

    kind: Literal["edit_data"]
    section: str
    table: str = "raw"
    set_column: str = Field(description="The column whose value to change.")
    set_value: str | None = Field(default=None, description="The new value (a literal).")
    where: str | None = Field(
        default=None,
        description="A boolean SQL expression selecting which rows to change, e.g. "
        "\"cohort\" = 'control'. Omit to change every row.",
    )


class DeleteData(_Step):
    """Propose deleting rows (a DELETE). Use ONLY when the user explicitly asks to
    delete/remove rows. Nothing happens until the user confirms."""

    kind: Literal["delete_data"]
    section: str
    table: str = "raw"
    where: str | None = Field(
        default=None,
        description="A boolean SQL expression selecting which rows to delete. "
        "Omit to delete every row (rarely what they want — be sure).",
    )


class Restructure(_Step):
    """Propose a structural change to a dataset (add / drop / rename a column).
    Use ONLY when the user explicitly asks to restructure the data. Nothing
    happens until the user confirms."""

    kind: Literal["restructure_data"]
    operation: Literal["add_column", "drop_column", "rename_column"]
    section: str
    table: str = "raw"
    column: str = Field(description="The column to add, drop, or rename.")
    new_name: str | None = Field(
        default=None, description="For rename_column: the new column name."
    )


class Answer(_Step):
    kind: Literal["answer"]


AgentStep = Annotated[
    Union[
        RunSql, MakeChart, RunStat, MakeFigure, CheckData, AskUser,
        EditData, DeleteData, Restructure, Answer,
    ],
    Field(discriminator="kind"),
]


class StepDecision(BaseModel):
    """What the model returns each loop iteration."""

    model_config = ConfigDict(extra="ignore")

    thought: str = Field(default="", description="One short sentence of reasoning.")
    step: AgentStep
