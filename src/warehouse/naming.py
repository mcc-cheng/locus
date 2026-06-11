"""Deterministic section-name derivation from filename + upload timestamp.

See docs/specs/phase-1.1-warehouse-isolation.md § "Section naming".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import PurePath

_NON_IDENT = re.compile(r"[^a-z0-9]+")
_MAX_BASE_LEN = 40

# Reserved schemas that a user section must never collide with.
RESERVED_SCHEMAS = frozenset({"_locus", "main", "information_schema", "pg_catalog", "system", "temp"})


def slugify_base(filename: str) -> str:
    """Turn a filename into a safe DuckDB identifier base (no timestamp suffix)."""
    stem = PurePath(filename).stem.lower()
    slug = _NON_IDENT.sub("_", stem).strip("_")
    if not slug:
        slug = "dataset"
    if not slug[0].isalpha():
        slug = f"s_{slug}"
    return slug[:_MAX_BASE_LEN].rstrip("_") or "dataset"


def _stamp(ts: datetime) -> str:
    """Render a UTC timestamp as a compact, identifier-safe suffix."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def derive_section_name(
    filename: str,
    upload_timestamp: datetime,
    *,
    existing: set[str] | None = None,
) -> str:
    """Derive a unique, deterministic section name.

    ``existing`` is the set of section names already present; if the derived name
    collides, ``_2``, ``_3``, … are appended until unique.
    """
    existing = existing or set()
    base = f"{slugify_base(filename)}__{_stamp(upload_timestamp)}"
    candidate = base
    n = 1
    while candidate in existing or candidate in RESERVED_SCHEMAS:
        n += 1
        candidate = f"{base}_{n}"
    return candidate
