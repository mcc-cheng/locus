"""The Locus warehouse: an on-disk DuckDB database aggregating isolated dataset
sections, with a sealed, non-destructive landing path.

Phase 1.1 scope: schema isolation + verbatim raw landing + the seal gate. The
read-only / clone policy arrives in Phase 1.3; here the warehouse is the
read-write *ingestion* handle.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import duckdb

from . import introspect
from .checkpoints import quote_ident, run_landing_checkpoint
from .csv_source import CsvReadOptions, read_source
from .errors import CheckpointError, SectionNotFoundError, SourceIntegrityError
from .models import CheckResult, SectionManifest
from .naming import derive_section_name
from .preservation import (
    discard_staged_source,
    preserve_source,
    verify_source,
)

DB_FILENAME = "warehouse.duckdb"
SOURCE_DIRNAME = "source"
META_SCHEMA = "_locus"
_SRC_REG = "_locus_landing_src"


@dataclass
class Staging:
    """A section mid-build inside an open transaction.

    Handed to ingestion engines so they can add relational structure to a freshly
    landed section on the same atomic transaction. ``con`` is the live read-write
    connection; ``section`` is the schema name; ``raw`` is always present.
    """

    con: duckdb.DuckDBPyConnection
    section: str
    csv_path: Path
    options: CsvReadOptions
    source_hash: str
    # Set by an ingestion engine (Phase 2) before the staging context exits.
    engine: str = "raw"
    contract_json: str | None = None

    def qualified(self, table: str) -> str:
        """Quoted ``"<section>"."<table>"`` reference."""
        q = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
        return f"{q(self.section)}.{q(table)}"


class Warehouse:
    """A read-write handle to a Locus warehouse directory."""

    def __init__(self, root: Path, con: duckdb.DuckDBPyConnection) -> None:
        self.root = root
        self.con = con

    # ---- lifecycle -------------------------------------------------------

    @classmethod
    def open(cls, root: str | Path, *, verify_sources: bool = True) -> "Warehouse":
        """Open (creating if needed) a warehouse directory.

        By default, re-verifies the SHA-256 of every preserved source file on
        launch (Phase 1.2) and raises ``SourceIntegrityError`` on any mismatch.
        Pass ``verify_sources=False`` for recovery tooling only.
        """
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        (root / SOURCE_DIRNAME).mkdir(exist_ok=True)
        con = duckdb.connect(str(root / DB_FILENAME))
        wh = cls(root, con)
        wh._ensure_meta()
        if verify_sources:
            results = wh.verify_sources()
            if any(not r.passed for r in results):
                wh.close()
                raise SourceIntegrityError(results)
        return wh

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def source_dir(self) -> Path:
        return self.root / SOURCE_DIRNAME

    def _ensure_meta(self) -> None:
        self.con.execute(f'CREATE SCHEMA IF NOT EXISTS {quote_ident(META_SCHEMA)}')
        self.con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {quote_ident(META_SCHEMA)}.sections (
                name VARCHAR PRIMARY KEY,
                source_filename VARCHAR NOT NULL,
                -- ISO-8601 UTC string; kept as text to avoid a pytz dependency
                -- for TIMESTAMPTZ round-tripping and any tz ambiguity.
                upload_timestamp VARCHAR NOT NULL,
                sha256 VARCHAR,
                csv_options VARCHAR NOT NULL,
                engine VARCHAR NOT NULL DEFAULT 'raw',
                contract VARCHAR
            )
            """
        )

    # ---- landing ---------------------------------------------------------

    def land_csv(
        self,
        csv_path: str | Path,
        upload_timestamp: datetime,
        *,
        csv_options: CsvReadOptions | None = None,
    ) -> SectionManifest:
        """Land a CSV verbatim into a new isolated section and seal it.

        Runs the Phase 1.1 non-regression checkpoint before sealing. On any check
        failure the section is rolled back entirely and ``CheckpointError`` is
        raised — nothing partial is left visible.
        """
        with self.staging(csv_path, upload_timestamp, csv_options=csv_options) as stg:
            # Phase 1.1 lands raw only; no further structure added here.
            section = stg.section
        return self.get_section(section)

    @contextmanager
    def staging(
        self,
        csv_path: str | Path,
        upload_timestamp: datetime,
        *,
        csv_options: CsvReadOptions | None = None,
    ) -> Iterator["Staging"]:
        """Atomic, all-or-nothing section build.

        Opens a new isolated section, preserves the source, lands the verbatim
        raw table, and runs the Phase 1.1 checkpoint. Yields a :class:`Staging`
        the caller can use to add relational structure (Phase 2) on the SAME
        transaction. On clean exit the section is registered and committed; on
        any exception (including a Phase-2 QC failure) everything is rolled back
        and the staged source is discarded — nothing partial is ever visible.

        Used directly by the ingestion engines; ``land_csv`` is the raw-only case.
        """
        csv_path = Path(csv_path)
        options = csv_options or CsvReadOptions()
        if upload_timestamp.tzinfo is None:
            upload_timestamp = upload_timestamp.replace(tzinfo=timezone.utc)

        section = derive_section_name(
            csv_path.name, upload_timestamp, existing=set(self._section_names())
        )
        # Phase 1.2: preserve the source bytes BEFORE any ingestion work.
        _dest, source_hash = preserve_source(self.source_dir, section, csv_path)

        self.con.execute("BEGIN TRANSACTION")
        try:
            self.con.execute(f"CREATE SCHEMA {quote_ident(section)}")
            rel = read_source(self.con, str(csv_path), options)
            self.con.register(_SRC_REG, rel)
            try:
                self.con.execute(
                    f'CREATE TABLE {quote_ident(section)}."raw" AS '
                    f"SELECT * FROM {_SRC_REG}"
                )
            finally:
                self.con.unregister(_SRC_REG)

            report = run_landing_checkpoint(self.con, section, str(csv_path), options)
            if not report.passed:
                raise CheckpointError(report)

            stg = Staging(
                con=self.con,
                section=section,
                csv_path=csv_path,
                options=options,
                source_hash=source_hash,
            )
            yield stg

            # Caller succeeded (Phase 2 structure, if any, is built and verified).
            self.con.execute(
                f"INSERT INTO {quote_ident(META_SCHEMA)}.sections "
                "(name, source_filename, upload_timestamp, sha256, csv_options, engine, contract) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    section,
                    csv_path.name,
                    upload_timestamp.isoformat(),
                    source_hash,
                    options.model_dump_json(),
                    stg.engine,
                    stg.contract_json,
                ],
            )
            self.con.execute("COMMIT")
        except Exception:
            try:
                self.con.execute("ROLLBACK")
            except duckdb.Error:
                pass
            discard_staged_source(self.source_dir, section)
            raise

    # ---- introspection (delegates to the shared read-only module) --------

    def _section_names(self) -> list[str]:
        return introspect.section_names(self.con)

    def list_sections(self) -> list[SectionManifest]:
        return introspect.all_section_manifests(self.con)

    def get_section(self, name: str) -> SectionManifest:
        return introspect.section_manifest(self.con, name)

    def drop_section(self, name: str) -> None:
        """Drop exactly one section. Other sections are untouched."""
        if name not in self._section_names():
            raise SectionNotFoundError(f"no section named {name!r}")
        self.con.execute(f"DROP SCHEMA IF EXISTS {quote_ident(name)} CASCADE")
        self.con.execute(
            f"DELETE FROM {quote_ident(META_SCHEMA)}.sections WHERE name = ?", [name]
        )

    # ---- source preservation (Phase 1.2) --------------------------------

    def source_path(self, section: str) -> Path:
        """Location of a section's preserved verbatim source copy."""
        man = self.get_section(section)  # raises SectionNotFoundError if unknown
        return self.source_dir / section / man.source_filename

    def verify_sources(self) -> tuple[CheckResult, ...]:
        """Re-hash every recorded source file and compare to its stored hash."""
        rows = self.con.execute(
            f"SELECT name, source_filename, sha256 "
            f"FROM {quote_ident(META_SCHEMA)}.sections ORDER BY name"
        ).fetchall()
        results: list[CheckResult] = []
        for name, filename, expected in rows:
            if expected is None:
                # Pre-Phase-1.2 sections (or in-flight) have no recorded hash.
                continue
            dest = self.source_dir / name / filename
            results.append(verify_source(dest, expected, section=name))
        return tuple(results)
