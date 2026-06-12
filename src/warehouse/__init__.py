"""Locus warehouse layer (Phase 1): isolated, non-destructive CSV storage."""

from .csv_source import CsvReadOptions
from .errors import (
    CheckpointError,
    ReadOnlyViolationError,
    SectionExistsError,
    SectionNotFoundError,
    SourceIntegrityError,
    WarehouseError,
)
from .models import (
    CheckpointReport,
    CheckResult,
    ColumnInfo,
    SectionManifest,
    TableInfo,
)
from .clone import Clone, CloneManager, cow_copy_database
from .preservation import sha256_file
from .readonly import CanonicalDB
from .warehouse import Warehouse

__all__ = [
    "Warehouse",
    "CsvReadOptions",
    "SectionManifest",
    "TableInfo",
    "ColumnInfo",
    "CheckResult",
    "CheckpointReport",
    "WarehouseError",
    "CheckpointError",
    "SectionExistsError",
    "SectionNotFoundError",
    "ReadOnlyViolationError",
    "SourceIntegrityError",
    "sha256_file",
    "CanonicalDB",
    "Clone",
    "CloneManager",
    "cow_copy_database",
]
