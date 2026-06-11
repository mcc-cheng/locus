"""Non-regression checkpoint for the raw landing (Phase 1.1).

These checks compare the *persisted* raw table against an *independent re-read*
of the source CSV using identical parse options. They are the gate an ingest
must clear before it is sealed.

Phase 1.1 defines two checks here:
  * row-count round-trip
  * distinct-value containment (stored ⊆ source, per column)

Phase 2.1 layers three more (orphan FKs, schema-contract match, referential
integrity) on top of the relational output.
"""

from __future__ import annotations

import duckdb

from .csv_source import CsvReadOptions, read_source
from .models import CheckpointReport, CheckResult

_SRC_VIEW = "_locus_chk_src"


def quote_ident(name: str) -> str:
    """Quote a DuckDB identifier, escaping embedded double quotes."""
    return '"' + name.replace('"', '""') + '"'


def _qualified(section: str, table: str) -> str:
    return f"{quote_ident(section)}.{quote_ident(table)}"


def _stored_columns(con: duckdb.DuckDBPyConnection, section: str, table: str) -> list[str]:
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
        """,
        [section, table],
    ).fetchall()
    return [r[0] for r in rows]


def check_row_count_roundtrip(
    con: duckdb.DuckDBPyConnection, section: str, table: str = "raw"
) -> CheckResult:
    """Stored row count must equal the re-read source row count.

    Assumes the source has been registered as ``_SRC_VIEW`` by the caller.
    """
    stored = con.execute(f"SELECT COUNT(*) FROM {_qualified(section, table)}").fetchone()[0]
    source = con.execute(f"SELECT COUNT(*) FROM {_SRC_VIEW}").fetchone()[0]
    return CheckResult(
        name="row_count_roundtrip",
        passed=stored == source,
        expected=str(source),
        actual=str(stored),
        detail=(
            "row counts match"
            if stored == source
            else f"stored {stored} rows but source has {source}"
        ),
    )


def check_distinct_value_containment(
    con: duckdb.DuckDBPyConnection, section: str, table: str = "raw"
) -> list[CheckResult]:
    """For each column, the stored distinct-value set must EQUAL the source's.

    The spec names this "distinct-value containment" (``stored ⊆ source`` — no
    value fabricated). Because the raw table's columns map 1:1 to the source, we
    assert the strong form: both ``stored ⊆ source`` AND ``source ⊆ stored``.

    The reverse direction is not redundant — a coercion that *collapses* two
    distinct source values into one (``"1.0"`` and ``"1.00"`` → ``"1"``) keeps
    the row count and satisfies ``stored ⊆ source``, yet corrupts the data. Only
    ``source ⊆ stored`` catches it.

    EXCEPT compares sets and treats NULLs as equal, which is exactly right here.
    """
    results: list[CheckResult] = []
    stored = _qualified(section, table)
    for col in _stored_columns(con, section, table):
        c = quote_ident(col)
        fabricated = con.execute(
            f"SELECT {c} FROM {stored} EXCEPT SELECT {c} FROM {_SRC_VIEW}"
        ).fetchall()
        lost = con.execute(
            f"SELECT {c} FROM {_SRC_VIEW} EXCEPT SELECT {c} FROM {stored}"
        ).fetchall()
        passed = not fabricated and not lost
        if passed:
            detail = "stored distinct values exactly match source"
        elif fabricated:
            detail = f"{len(fabricated)} stored value(s) not in source; e.g. {fabricated[0][0]!r}"
        else:
            detail = f"{len(lost)} source value(s) missing from store; e.g. {lost[0][0]!r}"
        results.append(
            CheckResult(
                name="distinct_value_containment",
                column=col,
                passed=passed,
                detail=detail,
            )
        )
    return results


def run_landing_checkpoint(
    con: duckdb.DuckDBPyConnection,
    section: str,
    csv_path: str,
    options: CsvReadOptions,
    *,
    table: str = "raw",
) -> CheckpointReport:
    """Run the full Phase 1.1 checkpoint against a freshly-landed raw table."""
    source_rel = read_source(con, csv_path, options)
    con.register(_SRC_VIEW, source_rel)
    try:
        checks: list[CheckResult] = [check_row_count_roundtrip(con, section, table)]
        checks.extend(check_distinct_value_containment(con, section, table))
    finally:
        con.unregister(_SRC_VIEW)
    return CheckpointReport(section=section, checks=tuple(checks))
