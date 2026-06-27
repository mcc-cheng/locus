"""Annulus ingestion engines (Phase 2): flat CSV -> verified relational model."""

from .agentic import AgenticIngestor, build_contract_from_proposal, build_profile
from .audit import IngestAudit, read_contract, write_audit, write_contract
from .biopack import (
    BIOPACK_WARNING,
    TRANSFORMS,
    BiopackError,
    BiopackUnavailableError,
)
from .contract import DerivedColumnSpec, ForeignKeySpec, StorageContract, TableSpec
from .deterministic import DeterministicIngestor, analyze
from .errors import IngestError, IngestRejected, OllamaUnavailableError, ProposalError
from .ollama_client import OllamaClient, OllamaConfig
from .proposal import ModelProposal, ProposedDimension, Proposer
from .qc import run_ingest_qc
from .result import IngestResult

__all__ = [
    "DeterministicIngestor",
    "AgenticIngestor",
    "analyze",
    "build_profile",
    "build_contract_from_proposal",
    "StorageContract",
    "TableSpec",
    "ForeignKeySpec",
    "DerivedColumnSpec",
    "BIOPACK_WARNING",
    "TRANSFORMS",
    "BiopackError",
    "BiopackUnavailableError",
    "IngestResult",
    "IngestAudit",
    "run_ingest_qc",
    "read_contract",
    "write_contract",
    "write_audit",
    "OllamaClient",
    "OllamaConfig",
    "ModelProposal",
    "ProposedDimension",
    "Proposer",
    "IngestError",
    "IngestRejected",
    "OllamaUnavailableError",
    "ProposalError",
]
