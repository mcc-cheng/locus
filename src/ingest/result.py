"""The result of a successful ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from warehouse.models import CheckpointReport, SectionManifest

from .contract import StorageContract


@dataclass(frozen=True)
class IngestResult:
    section: str
    manifest: SectionManifest
    contract: StorageContract
    qc: CheckpointReport
    contract_path: Path
    audit_path: Path
