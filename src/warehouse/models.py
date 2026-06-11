"""Immutable data contracts for the Locus warehouse layer (Phase 1).

Every object the warehouse hands back to callers is one of these frozen Pydantic
models. They are the stable contract that the service layer, API, and frontend
(Phases 3–6) build against.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    """Base for immutable contract models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ColumnInfo(_Frozen):
    """A single column in a stored table."""

    name: str
    ordinal: int = Field(ge=0, description="Zero-based position, matching CSV header order.")
    stored_type: str = Field(
        description="DuckDB type the value is stored as. Always 'VARCHAR' for the raw table.",
    )


class TableInfo(_Frozen):
    """A table inside a section schema."""

    name: str
    row_count: int = Field(ge=0)
    columns: tuple[ColumnInfo, ...]


class SectionManifest(_Frozen):
    """Everything known about one isolated dataset section.

    `sha256` is populated by Phase 1.2 (source preservation); it is ``None`` until
    a verbatim source copy has been recorded.
    """

    name: str = Field(description="DuckDB schema name for this section.")
    source_filename: str = Field(description="Original uploaded filename, unmodified.")
    upload_timestamp: datetime
    tables: tuple[TableInfo, ...]
    sha256: str | None = Field(
        default=None,
        description="SHA-256 of the preserved source file (Phase 1.2); None if not yet recorded.",
    )

    @property
    def raw(self) -> TableInfo:
        """The verbatim raw landing table for this section."""
        for t in self.tables:
            if t.name == "raw":
                return t
        raise LookupError(f"section {self.name!r} has no raw table")


class CheckResult(_Frozen):
    """Outcome of a single non-regression / QC check."""

    name: str
    passed: bool
    detail: str = ""
    expected: str | None = None
    actual: str | None = None
    # Optional column scope for per-column checks (e.g. distinct-value containment).
    column: str | None = None


class CheckpointReport(_Frozen):
    """The collected result of running a checkpoint (a set of checks)."""

    section: str
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """True only if every check passed unanimously."""
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)
