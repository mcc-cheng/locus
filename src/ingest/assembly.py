"""Mechanical, deterministic assembly of a relational model from raw.

This module does NO decision-making — it only executes a Storage Contract
against the verbatim ``raw`` table and exposes the data-shape primitives an
engine needs to *make* decisions. Both the deterministic engine and the agentic
engine (whose semantic decisions are the only difference) build through here, so
the bytes-faithful mechanics are identical and tested once.
"""

from __future__ import annotations

import duckdb

from warehouse.checkpoints import quote_ident

from .contract import StorageContract


def _q(section: str, table: str) -> str:
    return f"{quote_ident(section)}.{quote_ident(table)}"


def raw_columns(con: duckdb.DuckDBPyConnection, section: str) -> list[str]:
    """Source column names in header order."""
    return [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = 'raw' ORDER BY ordinal_position",
            [section],
        ).fetchall()
    ]


def row_count(con: duckdb.DuckDBPyConnection, section: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {_q(section, 'raw')}").fetchone()[0]


def column_stats(con: duckdb.DuckDBPyConnection, section: str) -> dict[str, tuple[int, int]]:
    """Per source column, return ``(distinct_including_null, null_count)``."""
    stats: dict[str, tuple[int, int]] = {}
    for col in raw_columns(con, section):
        c = quote_ident(col)
        distinct, nulls = con.execute(
            f"SELECT COUNT(DISTINCT {c}) + "
            f"(CASE WHEN COUNT(*) FILTER (WHERE {c} IS NULL) > 0 THEN 1 ELSE 0 END), "
            f"COUNT(*) FILTER (WHERE {c} IS NULL) "
            f"FROM {_q(section, 'raw')}"
        ).fetchone()
        stats[col] = (distinct, nulls)
    return stats


def functional_dependency(
    con: duckdb.DuckDBPyConnection, section: str, determinant: str, dependent: str
) -> bool:
    """True iff ``determinant -> dependent`` holds in raw (NULL-aware).

    Holds when every value of ``determinant`` maps to exactly one value of
    ``dependent`` (treating NULL as a value).
    """
    k = quote_ident(determinant)
    a = quote_ident(dependent)
    max_distinct = con.execute(
        f"SELECT MAX(d) FROM ("
        f"  SELECT COUNT(DISTINCT {a}) + "
        f"  (CASE WHEN COUNT(*) FILTER (WHERE {a} IS NULL) > 0 THEN 1 ELSE 0 END) AS d "
        f"  FROM {_q(section, 'raw')} GROUP BY {k}"
        f")"
    ).fetchone()[0]
    return max_distinct is None or max_distinct <= 1


def build_relational(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> None:
    """Materialize the contract's fact + dimension tables from raw, verbatim.

    Dimensions are ``SELECT DISTINCT`` over their columns (one row per key); the
    fact is a straight projection of raw (one row per raw row). No value is ever
    transformed — only selected (and possibly renamed to ``<col>_raw`` when a
    biopack transform claims the original name). Derived (biopack) columns are NOT
    built here — ``biopack.apply`` adds and computes them afterward.
    """
    rel_to_source = {contract.verbatim_name(c): c for c in contract.source_columns}
    derived = contract.derived_names

    def column_expr(rel: str) -> str | None:
        if rel in derived:
            return None  # added later by biopack
        src = rel_to_source[rel]
        return quote_ident(rel) if src == rel else f"{quote_ident(src)} AS {quote_ident(rel)}"

    def projection(columns: tuple[str, ...]) -> str:
        return ", ".join(e for e in (column_expr(c) for c in columns) if e)

    raw = _q(section, "raw")
    for t in contract.tables:
        if t.role == "dimension":
            con.execute(
                f"CREATE TABLE {_q(section, t.name)} AS "
                f"SELECT DISTINCT {projection(t.columns)} FROM {raw}"
            )
    fact = contract.table(contract.fact_table)
    con.execute(
        f"CREATE TABLE {_q(section, fact.name)} AS SELECT {projection(fact.columns)} FROM {raw}"
    )
