"""Audit ledger for an ingest (Phases 2.1 / 2.2).

A human-readable, machine-checkable record of exactly what an engine did: the
sealed contract, the decisions that produced it, and the QC verdict. Written to
``<root>/audit/<section>.audit.json`` only after a successful seal.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from warehouse.models import CheckResult

from .contract import StorageContract


class IngestAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    section: str
    engine: str
    source_filename: str
    sha256: str
    upload_timestamp: str
    contract: StorageContract
    qc_passed: bool
    qc_checks: tuple[CheckResult, ...]
    decisions: tuple[str, ...] = ()
    model: str | None = None  # agentic engine: the Ollama model used
    notes: tuple[str, ...] = ()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_contract(path: Path, contract: StorageContract) -> None:
    _atomic_write(path, contract.model_dump_json(indent=2))


def write_audit(path: Path, audit: IngestAudit) -> None:
    _atomic_write(path, audit.model_dump_json(indent=2))


def read_contract(path: Path) -> StorageContract:
    return StorageContract.model_validate(json.loads(path.read_text(encoding="utf-8")))
