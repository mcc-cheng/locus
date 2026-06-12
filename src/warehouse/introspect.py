"""Read-only introspection of a warehouse connection.

Pure read functions over any DuckDB connection (read-only or read-write). Shared
by ``Warehouse`` (read-write handle) and the service layer (read-only). No
mutations, ever.
"""

from __future__ import annotations

from datetime import datetime

import duckdb

from .checkpoints import quote_ident
from .errors import SectionNotFoundError
from .models import ColumnInfo, SectionManifest, TableInfo

META_SCHEMA = "_locus"


def section_names(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        f"SELECT name FROM {quote_ident(META_SCHEMA)}.sections ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def tables_for(con: duckdb.DuckDBPyConnection, section: str) -> tuple[TableInfo, ...]:
    table_rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = ? ORDER BY table_name",
        [section],
    ).fetchall()
    tables: list[TableInfo] = []
    for (tname,) in table_rows:
        col_rows = con.execute(
            "SELECT column_name, ordinal_position, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [section, tname],
        ).fetchall()
        columns = tuple(
            # information_schema ordinal_position is 1-based; expose 0-based.
            ColumnInfo(name=c[0], ordinal=c[1] - 1, stored_type=c[2])
            for c in col_rows
        )
        n = con.execute(
            f"SELECT COUNT(*) FROM {quote_ident(section)}.{quote_ident(tname)}"
        ).fetchone()[0]
        tables.append(TableInfo(name=tname, row_count=n, columns=columns))
    return tuple(tables)


def section_manifest(con: duckdb.DuckDBPyConnection, name: str) -> SectionManifest:
    row = con.execute(
        f"SELECT name, source_filename, upload_timestamp, sha256 "
        f"FROM {quote_ident(META_SCHEMA)}.sections WHERE name = ?",
        [name],
    ).fetchone()
    if row is None:
        raise SectionNotFoundError(f"no section named {name!r}")
    return SectionManifest(
        name=row[0],
        source_filename=row[1],
        upload_timestamp=datetime.fromisoformat(row[2]),
        sha256=row[3],
        tables=tables_for(con, name),
    )


def all_section_manifests(con: duckdb.DuckDBPyConnection) -> list[SectionManifest]:
    return [section_manifest(con, n) for n in section_names(con)]
