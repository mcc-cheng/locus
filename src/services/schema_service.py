"""Schema service (Phase 3.1).

Read-only. Returns the structure of every dataset in a sealed warehouse:
sections, their tables, columns + (inferred) types, row counts, upload
timestamp, source filename, and SHA-256. No mutations.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from warehouse import CanonicalDB, SectionManifest
from warehouse import introspect
from warehouse.checkpoints import quote_ident
from warehouse.warehouse import META_SCHEMA, SOURCE_DIRNAME

from .models import DatasetSummary, WarehouseSummary


class SchemaService:
    """Read-only structural view of a warehouse."""

    def __init__(self, canonical: CanonicalDB) -> None:
        self._db = canonical
        self._root = canonical.path.parent

    @classmethod
    def open(cls, root: str | Path) -> "SchemaService":
        return cls(CanonicalDB.open(root))

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SchemaService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- structure -------------------------------------------------------

    def list_datasets(self) -> list[SectionManifest]:
        return introspect.all_section_manifests(self._db.con)

    def get_dataset(self, section: str) -> SectionManifest:
        """Raises ``SectionNotFoundError`` if unknown."""
        return introspect.section_manifest(self._db.con, section)

    # ---- overview (Home tab) --------------------------------------------

    def summary(self) -> WarehouseSummary:
        rows = self._db.con.execute(
            f"SELECT name, source_filename, upload_timestamp, sha256, engine "
            f"FROM {quote_ident(META_SCHEMA)}.sections ORDER BY upload_timestamp, name"
        ).fetchall()
        datasets: list[DatasetSummary] = []
        total_rows = 0
        total_bytes = 0
        for name, filename, uploaded, sha, engine in rows:
            raw_rows = self._db.con.execute(
                f"SELECT COUNT(*) FROM {quote_ident(name)}.\"raw\""
            ).fetchone()[0]
            table_count = self._db.con.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ?",
                [name],
            ).fetchone()[0]
            source_file = self._root / SOURCE_DIRNAME / name / filename
            source_bytes = source_file.stat().st_size if source_file.exists() else 0
            total_rows += raw_rows
            total_bytes += source_bytes
            datasets.append(
                DatasetSummary(
                    name=name,
                    source_filename=filename,
                    upload_timestamp=datetime.fromisoformat(uploaded),
                    engine=engine,
                    row_count=raw_rows,
                    table_count=table_count,
                    source_bytes=source_bytes,
                    sha256=sha,
                )
            )
        return WarehouseSummary(
            dataset_count=len(datasets),
            total_rows=total_rows,
            total_source_bytes=total_bytes,
            datasets=tuple(datasets),
        )
