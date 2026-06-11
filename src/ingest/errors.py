"""Ingestion-engine exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warehouse.models import CheckpointReport


class IngestError(Exception):
    """Base for ingestion errors."""


class IngestRejected(IngestError):
    """The five-check QC gate did not pass unanimously; the ingest was rejected.

    Raised inside the staging transaction so the whole section is rolled back and
    the staged source discarded — nothing partial is sealed.
    """

    def __init__(self, report: "CheckpointReport") -> None:
        self.report = report
        failed = "; ".join(
            f"{c.name}" + (f"[{c.column}]" if c.column else "") + (f": {c.detail}" if c.detail else "")
            for c in report.failures
        )
        super().__init__(
            f"ingest rejected for section {report.section!r} — "
            f"{len(report.failures)} QC check(s) failed: {failed}"
        )


class OllamaUnavailableError(IngestError):
    """The agentic engine could not reach Ollama or the required model.

    Carries actionable setup instructions; the engine never silently falls back.
    This is an *availability* failure — it blocks the ingest.
    """


class ProposalError(IngestError):
    """Ollama was reachable but returned no usable semantic proposal.

    Distinct from ``OllamaUnavailableError``: the backend is up, so the engine may
    degrade to deterministic structure (recorded in the audit) rather than block.
    """
