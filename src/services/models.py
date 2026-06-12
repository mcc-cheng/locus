"""Response models for the service layer (Phase 3).

These are the shapes the REST API and frontend build against. All frozen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


ChartType = Literal["histogram", "bar", "heatmap", "dose_response", "scatter"]
Aggregate = Literal["count", "sum", "avg", "min", "max"]


class ChartRequest(BaseModel):
    """A visualization request. Column roles vary by chart type; see the service
    for which roles each type requires."""

    model_config = ConfigDict(extra="forbid")

    type: ChartType
    section: str
    table: str = "fact"
    # Column roles (used selectively per chart type).
    x: str | None = None
    y: str | None = None
    color: str | None = None  # series / category grouping
    row: str | None = None  # heatmap row (e.g. plate row)
    col: str | None = None  # heatmap column (e.g. plate column)
    value: str | None = None  # heatmap measured value
    aggregate: Aggregate = "count"
    bins: int = Field(default=30, ge=2, le=200)


class VisualizationResult(_Frozen):
    spec: dict[str, Any] = Field(description="A Vega-Lite spec with inline aggregated data.")
    data: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = Field(default=False, description="True if the 10,000-row cap was hit.")
    execution_ms: float = 0.0


class DatasetSummary(_Frozen):
    """One row of the Home/overview list (derived from GET /schema)."""

    name: str
    source_filename: str
    upload_timestamp: datetime
    engine: str
    row_count: int = Field(ge=0, description="Rows in the verbatim raw table.")
    table_count: int = Field(ge=0)
    source_bytes: int = Field(ge=0, description="Size of the preserved source file.")
    sha256: str | None = None
    status: str = "sealed"


class WarehouseSummary(_Frozen):
    dataset_count: int = Field(ge=0)
    total_rows: int = Field(ge=0)
    total_source_bytes: int = Field(ge=0)
    datasets: tuple[DatasetSummary, ...] = ()
