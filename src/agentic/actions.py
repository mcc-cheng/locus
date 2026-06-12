"""The analyst agent's action types (Phase 5.2).

Exactly four shapes are permitted. The agent loop parses the model's output into
this strict, discriminated union — anything that doesn't match one of the four
(wrong/extra fields, unknown ``type``) raises a ``ValidationError`` and is
rejected **before execution**. The loop validates; the model never executes
anything directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

StatTest = Literal[
    "ttest_ind", "ttest_rel", "mannwhitneyu", "pearsonr", "spearmanr", "f_oneway"
]
ChartType = Literal["histogram", "bar", "heatmap", "dose_response", "scatter"]
Aggregate = Literal["count", "sum", "avg", "min", "max"]


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QueryAction(_Action):
    """Run a read-only SQL SELECT and return rows."""

    type: Literal["query"]
    sql: str


class ChartAction(_Action):
    """Request a server-aggregated chart. The agent chooses type + columns; the
    visualization service builds the (capped, server-side) Vega-Lite spec — the
    agent can never embed full-table data."""

    type: Literal["chart"]
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


class StatTestAction(_Action):
    """Run a named statistical test inside a sandbox (never on the canonical)."""

    type: Literal["stat_test"]
    test: StatTest
    section: str
    table: str = "raw"
    columns: tuple[str, ...] = Field(min_length=1)
    group_by: str | None = None
    sandbox_id: str


class NarrativeAction(_Action):
    """A plain-language answer with no database access."""

    type: Literal["narrative"]
    text: str


AgentAction = Annotated[
    Union[QueryAction, ChartAction, StatTestAction, NarrativeAction],
    Field(discriminator="type"),
]


class AgentDecision(BaseModel):
    """What the model returns: a framing sentence plus exactly one action."""

    model_config = ConfigDict(extra="ignore")

    narration: str = ""
    action: AgentAction


class AgentResponse(BaseModel):
    """What the agent returns to the caller for one turn."""

    model_config = ConfigDict(frozen=True)

    response: str
    action_type: Literal["query", "chart", "stat_test", "narrative"]
    sql: str | None = None
    spec: dict[str, Any] | None = None
    result: Any = None
    error: str | None = None
    # For chart actions: the request that produced the spec, so the UI can
    # re-open it in the Visualize tab.
    chart_request: dict[str, Any] | None = None
