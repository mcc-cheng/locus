"""Warehouse-layer exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CheckpointReport


class WarehouseError(Exception):
    """Base for all warehouse errors."""


class SectionExistsError(WarehouseError):
    """A section with the derived name already exists and could not be disambiguated."""


class SectionNotFoundError(WarehouseError):
    """No section with the requested name exists."""


class CheckpointError(WarehouseError):
    """A non-regression checkpoint failed; the ingest was not sealed.

    Carries the full report so callers can surface exactly which checks failed.
    """

    def __init__(self, report: "CheckpointReport") -> None:
        self.report = report
        failed = ", ".join(
            f"{c.name}" + (f"[{c.column}]" if c.column else "") for c in report.failures
        )
        super().__init__(
            f"checkpoint failed for section {report.section!r}: {failed}. "
            "Ingest was rejected; no data was sealed."
        )


class ReadOnlyViolationError(WarehouseError):
    """An attempt was made to write through a read-only canonical connection."""


class SourceIntegrityError(WarehouseError):
    """One or more preserved source files failed SHA-256 verification on launch."""

    def __init__(self, results) -> None:
        self.results = tuple(results)
        bad = ", ".join(r.column for r in self.results if not r.passed)
        super().__init__(
            f"source integrity check failed for section(s): {bad}. "
            "The warehouse may be corrupted or tampered with; refusing to open."
        )
