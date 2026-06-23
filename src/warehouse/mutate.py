"""Deterministic, parameterized mutations on a dataset's editable ``raw`` table.

This is the *only* write path the analyst agent can reach, and it is reached
ONLY after an explicit human confirmation in the API layer — the LLM never calls
these functions directly. Each operation is a plain, auditable DuckDB statement:

  * ``update_where`` / ``delete_where`` — value edits and row deletes, addressed
    by a WHERE expression (the value is always bound as a parameter, never
    interpolated).
  * ``add_column`` / ``drop_column`` / ``rename_column`` — schema restructuring.

The **preserved source copy** (Phase 1.2) is never touched, so the original
upload stays byte-for-byte recoverable no matter what is edited here.
"""

from __future__ import annotations

import duckdb

from .checkpoints import quote_ident


def _raw(section: str, table: str = "raw") -> str:
    return f"{quote_ident(section)}.{quote_ident(table)}"


def columns(con: duckdb.DuckDBPyConnection, section: str, table: str = "raw") -> list[str]:
    return [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [section, table],
        ).fetchall()
    ]


def _require_column(con, section, table, col: str) -> None:
    if col not in columns(con, section, table):
        raise ValueError(f"no column {col!r} in {section}.{table}")


def normalize_where(where: str | None) -> str | None:
    """Validate a user/agent-supplied WHERE expression. It must be a single
    boolean expression — never a chained statement. Returns the cleaned text, or
    None to mean "all rows" (the confirmation prompt always states the count, so
    an unscoped change is still explicit)."""
    if where is None:
        return None
    w = where.strip().replace("`", '"')
    if not w:
        return None
    # A WHERE clause is one expression; a semicolon means someone tried to chain
    # a second statement. Reject it outright rather than risk a stacked DELETE.
    if ";" in w:
        raise ValueError("WHERE may not contain ';' (only a single boolean expression)")
    if w.lower().startswith("where "):
        w = w[6:].strip()
    return w or None


def affected_count(
    con: duckdb.DuckDBPyConnection, section: str, table: str, where: str | None
) -> int:
    where = normalize_where(where)
    sql = f"SELECT COUNT(*) FROM {_raw(section, table)}"
    if where:
        sql += f" WHERE {where}"
    return int(con.execute(sql).fetchone()[0])


def update_where(
    con: duckdb.DuckDBPyConnection,
    section: str,
    table: str,
    set_column: str,
    value,
    where: str | None,
) -> int:
    """Set ``set_column`` to ``value`` (bound parameter) for matching rows.
    Returns the number of rows changed."""
    _require_column(con, section, table, set_column)
    where = normalize_where(where)
    n = affected_count(con, section, table, where)
    sql = f"UPDATE {_raw(section, table)} SET {quote_ident(set_column)} = ?"
    if where:
        sql += f" WHERE {where}"
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(sql, [value])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


def delete_where(
    con: duckdb.DuckDBPyConnection, section: str, table: str, where: str | None
) -> int:
    """Delete matching rows. Returns the number of rows deleted."""
    where = normalize_where(where)
    n = affected_count(con, section, table, where)
    sql = f"DELETE FROM {_raw(section, table)}"
    if where:
        sql += f" WHERE {where}"
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(sql)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


def add_column(con: duckdb.DuckDBPyConnection, section: str, table: str, column: str) -> None:
    """Add a new TEXT column (everything in raw is stored verbatim as text)."""
    if not column.strip():
        raise ValueError("column name is required")
    if column in columns(con, section, table):
        raise ValueError(f"column {column!r} already exists")
    con.execute(f"ALTER TABLE {_raw(section, table)} ADD COLUMN {quote_ident(column)} VARCHAR")


def add_computed_column(
    con: duckdb.DuckDBPyConnection, section: str, table: str, column: str, formula: str
) -> int:
    """Add a column whose values are computed from a SQL expression over the other
    columns (the spreadsheet-"formula" feature). The expression is evaluated once
    per row and the result stored verbatim as text. Returns the number of rows
    filled. Atomic: if the formula is invalid, the column is not left behind."""
    if not column.strip():
        raise ValueError("column name is required")
    if column in columns(con, section, table):
        raise ValueError(f"column {column!r} already exists")
    f = formula.strip().replace("`", '"')
    if not f:
        raise ValueError("a formula is required")
    if ";" in f:
        raise ValueError("a formula may not contain ';' (only a single expression)")
    raw = _raw(section, table)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"ALTER TABLE {raw} ADD COLUMN {quote_ident(column)} VARCHAR")
        con.execute(f"UPDATE {raw} SET {quote_ident(column)} = ({f})")
        n = int(con.execute(f"SELECT COUNT(*) FROM {raw}").fetchone()[0])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")  # also removes the half-added column
        raise
    return n


def drop_column(con: duckdb.DuckDBPyConnection, section: str, table: str, column: str) -> None:
    _require_column(con, section, table, column)
    if len(columns(con, section, table)) <= 1:
        raise ValueError("cannot drop the only column")
    con.execute(f"ALTER TABLE {_raw(section, table)} DROP COLUMN {quote_ident(column)}")


def rename_column(
    con: duckdb.DuckDBPyConnection, section: str, table: str, column: str, new_name: str
) -> None:
    _require_column(con, section, table, column)
    if not new_name.strip():
        raise ValueError("new column name is required")
    if new_name in columns(con, section, table):
        raise ValueError(f"column {new_name!r} already exists")
    con.execute(
        f"ALTER TABLE {_raw(section, table)} "
        f"RENAME COLUMN {quote_ident(column)} TO {quote_ident(new_name)}"
    )
