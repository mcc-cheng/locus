"""Row-level read/write on a dataset's verbatim ``raw`` table.

This is the editable-data-store surface: append, update, and delete individual
rows, addressed by DuckDB's stable per-row ``rowid``. Reads run on a read-only
connection; writes on the read-write warehouse connection.

Note: the **preserved source copy** (Phase 1.2) is never touched — the original
upload remains byte-for-byte recoverable even as the working table is edited.
"""

from __future__ import annotations

import duckdb

from .checkpoints import quote_ident


def _raw(section: str) -> str:
    return f'{quote_ident(section)}."raw"'


def columns(con: duckdb.DuckDBPyConnection, section: str) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = 'raw' ORDER BY ordinal_position",
            [section],
        ).fetchall()
    ]


def read_rows(con: duckdb.DuckDBPyConnection, section: str, *, offset: int = 0, limit: int = 100) -> dict:
    cols = columns(con, section)
    sel = ", ".join(quote_ident(c) for c in cols)
    raw = _raw(section)
    rows = con.execute(
        f"SELECT rowid AS _rid, {sel} FROM {raw} ORDER BY rowid LIMIT ? OFFSET ?",
        [limit, offset],
    ).fetchall()
    total = con.execute(f"SELECT COUNT(*) FROM {raw}").fetchone()[0]
    return {
        "columns": cols,
        "rows": [{"rid": r[0], "cells": list(r[1:])} for r in rows],
        "total": total,
        "offset": offset,
    }


def append_row(con: duckdb.DuckDBPyConnection, section: str, values: dict) -> int:
    cols = columns(con, section)
    collist = ", ".join(quote_ident(c) for c in cols)
    placeholders = ", ".join(["?"] * len(cols))
    params = [values.get(c) for c in cols]
    raw = _raw(section)
    con.execute(f"INSERT INTO {raw} ({collist}) VALUES ({placeholders})", params)
    # DuckDB never reuses rowids and appends increase them, so the new row has
    # the largest rowid. (RETURNING rowid is unsupported.)
    return con.execute(f"SELECT max(rowid) FROM {raw}").fetchone()[0]


def update_cell(con: duckdb.DuckDBPyConnection, section: str, rid: int, column: str, value) -> None:
    if column not in columns(con, section):
        raise KeyError(column)
    con.execute(
        f"UPDATE {_raw(section)} SET {quote_ident(column)} = ? WHERE rowid = ?", [value, rid]
    )


def delete_row(con: duckdb.DuckDBPyConnection, section: str, rid: int) -> bool:
    before = con.execute(f"SELECT COUNT(*) FROM {_raw(section)} WHERE rowid = ?", [rid]).fetchone()[0]
    con.execute(f"DELETE FROM {_raw(section)} WHERE rowid = ?", [rid])
    return before > 0
