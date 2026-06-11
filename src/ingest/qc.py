"""The five QC checks an ingest must pass unanimously to seal (Phase 2.1).

All five compare the engine's *relational model* (the ``fact`` + ``dim_*`` tables
described by the Storage Contract) against the verbatim ``raw`` table. ``raw`` was
already proven byte-faithful to the source CSV by the Phase 1.1 landing
checkpoint during staging, so it is the trusted baseline here.

  1. row_count_roundtrip      — fact has exactly one row per raw row
  2. zero_orphan_fks          — every FK value resolves to a dimension PK
  3. distinct_value_containment — no value fabricated or lost, per source column
  4. schema_contract_match    — the physical schema equals the declared contract
  5. referential_integrity    — fact ⋈ dims reconstructs raw EXACTLY (multiset)

Check #5 is the master guarantee: whatever normalization the engine chose, the
data round-trips losslessly or the ingest is rejected.
"""

from __future__ import annotations

import duckdb

from warehouse.checkpoints import quote_ident
from warehouse.models import CheckpointReport, CheckResult

from .contract import StorageContract


def _q(section: str, table: str) -> str:
    return f"{quote_ident(section)}.{quote_ident(table)}"


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    return con.execute(sql).fetchone()[0]


def check_row_count_roundtrip(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> CheckResult:
    fact = _scalar(con, f"SELECT COUNT(*) FROM {_q(section, contract.fact_table)}")
    raw = _scalar(con, f"SELECT COUNT(*) FROM {_q(section, 'raw')}")
    return CheckResult(
        name="row_count_roundtrip",
        passed=fact == raw,
        expected=str(raw),
        actual=str(fact),
        detail="fact row count matches raw" if fact == raw else "fact/raw row count drift",
    )


def check_zero_orphan_fks(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> list[CheckResult]:
    results: list[CheckResult] = []
    if not contract.foreign_keys:
        results.append(
            CheckResult(name="zero_orphan_fks", passed=True, detail="no foreign keys declared")
        )
        return results
    for fk in contract.foreign_keys:
        on = " AND ".join(
            f"f.{quote_ident(c)} IS NOT DISTINCT FROM d.{quote_ident(rc)}"
            for c, rc in zip(fk.columns, fk.ref_columns)
        )
        # Anti-join: count fact rows whose FK has no matching dimension PK.
        orphans = _scalar(
            con,
            f"SELECT COUNT(*) FROM {_q(section, fk.table)} f "
            f"LEFT JOIN {_q(section, fk.ref_table)} d ON {on} "
            f"WHERE d.{quote_ident(fk.ref_columns[0])} IS NULL "
            f"AND f.{quote_ident(fk.columns[0])} IS NOT NULL",
        )
        results.append(
            CheckResult(
                name="zero_orphan_fks",
                column=f"{fk.table}.{','.join(fk.columns)}->{fk.ref_table}",
                passed=orphans == 0,
                actual=str(orphans),
                detail="all FK values resolve" if orphans == 0 else f"{orphans} orphan FK row(s)",
            )
        )
    return results


def check_distinct_value_containment(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> list[CheckResult]:
    """For each source column, the distinct values across the relational model
    must EQUAL the distinct values in raw (nothing fabricated, nothing lost)."""
    results: list[CheckResult] = []
    for col in contract.source_columns:
        rel = contract.verbatim_name(col)  # biopack may preserve it under col_raw
        owners = [t.name for t in contract.tables if rel in t.columns]
        if not owners:
            results.append(
                CheckResult(
                    name="distinct_value_containment",
                    column=col,
                    passed=False,
                    detail="source column missing from every relational table",
                )
            )
            continue
        rc = quote_ident(rel)
        c = quote_ident(col)
        union = " UNION ".join(f"SELECT {rc} FROM {_q(section, t)}" for t in owners)
        raw_sel = f"SELECT {c} FROM {_q(section, 'raw')}"
        fabricated = _scalar(con, f"SELECT COUNT(*) FROM (({union}) EXCEPT ({raw_sel}))")
        lost = _scalar(con, f"SELECT COUNT(*) FROM (({raw_sel}) EXCEPT ({union}))")
        passed = fabricated == 0 and lost == 0
        if passed:
            detail = "distinct values match raw"
        elif fabricated:
            detail = f"{fabricated} fabricated distinct value(s)"
        else:
            detail = f"{lost} distinct value(s) lost"
        results.append(
            CheckResult(name="distinct_value_containment", column=col, passed=passed, detail=detail)
        )
    return results


def check_schema_contract_match(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> CheckResult:
    """Physical tables/columns must equal the declared contract (plus raw)."""
    phys_tables = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
            [section],
        ).fetchall()
    }
    expected = {t.name for t in contract.tables} | {"raw"}
    if phys_tables != expected:
        return CheckResult(
            name="schema_contract_match",
            passed=False,
            expected=str(sorted(expected)),
            actual=str(sorted(phys_tables)),
            detail="table set differs from contract",
        )
    for t in contract.tables:
        phys_cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ?",
                [section, t.name],
            ).fetchall()
        }
        if phys_cols != set(t.columns):
            return CheckResult(
                name="schema_contract_match",
                column=t.name,
                passed=False,
                expected=str(sorted(t.columns)),
                actual=str(sorted(phys_cols)),
                detail=f"columns of {t.name!r} differ from contract",
            )
    return CheckResult(
        name="schema_contract_match", passed=True, detail="physical schema matches contract"
    )


def _reconstruction_sql(section: str, contract: StorageContract) -> str:
    """Build a SELECT that reconstructs raw from fact ⋈ dims, in source order."""
    fact = contract.fact_table
    fact_cols = set(contract.table(fact).columns)
    # Alias the fact "f" and each referenced dim "d0", "d1", ...
    joins = []
    dim_alias: dict[str, str] = {}
    for i, fk in enumerate(contract.foreign_keys):
        alias = f"d{i}"
        dim_alias[fk.ref_table] = alias
        on = " AND ".join(
            f"f.{quote_ident(c)} IS NOT DISTINCT FROM {alias}.{quote_ident(rc)}"
            for c, rc in zip(fk.columns, fk.ref_columns)
        )
        joins.append(f"LEFT JOIN {_q(section, fk.ref_table)} {alias} ON {on}")

    # Reconstruct using each source column's VERBATIM representative (which biopack
    # may have renamed to <col>_raw). Derived columns are never selected here.
    # Alias each selected column back to its SOURCE name so the reconstruction's
    # columns line up positionally and by-name with raw (biopack renames vanish).
    select_terms = []
    for col in contract.source_columns:
        rel = contract.verbatim_name(col)
        out = quote_ident(col)
        if rel in fact_cols:
            select_terms.append(f"f.{quote_ident(rel)} AS {out}")
        else:
            owner = next(t for t in contract.tables if t.role == "dimension" and rel in t.columns)
            alias = dim_alias.get(owner.name)
            if alias is None:  # dimension not reachable via a declared FK
                raise ValueError(f"dimension {owner.name!r} has no foreign key from fact")
            select_terms.append(f"{alias}.{quote_ident(rel)} AS {out}")
    return (
        f"SELECT {', '.join(select_terms)} FROM {_q(section, fact)} f " + " ".join(joins)
    ).strip()


def check_referential_integrity(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> CheckResult:
    """fact ⋈ dims must reproduce raw exactly, as a MULTISET (duplicates and all)."""
    cols = ", ".join(quote_ident(c) for c in contract.source_columns)
    recon = _reconstruction_sql(section, contract)
    raw = f"SELECT {cols} FROM {_q(section, 'raw')}"
    # Group both sides by all columns with counts; compare the count-tuples.
    a = f"SELECT {cols}, COUNT(*) AS _n FROM ({recon}) GROUP BY ALL"
    b = f"SELECT {cols}, COUNT(*) AS _n FROM ({raw}) GROUP BY ALL"
    diff = _scalar(
        con,
        f"SELECT (SELECT COUNT(*) FROM (({a}) EXCEPT ({b}))) "
        f"+ (SELECT COUNT(*) FROM (({b}) EXCEPT ({a})))",
    )
    return CheckResult(
        name="referential_integrity",
        passed=diff == 0,
        actual=str(diff),
        detail=(
            "fact ⋈ dims reconstructs raw exactly"
            if diff == 0
            else f"{diff} row-group(s) differ between reconstruction and raw"
        ),
    )


def run_ingest_qc(
    con: duckdb.DuckDBPyConnection, section: str, contract: StorageContract
) -> CheckpointReport:
    """Run all five QC checks. Report passes only if every check passes."""
    checks: list[CheckResult] = [check_row_count_roundtrip(con, section, contract)]
    checks.extend(check_zero_orphan_fks(con, section, contract))
    checks.extend(check_distinct_value_containment(con, section, contract))
    checks.append(check_schema_contract_match(con, section, contract))
    checks.append(check_referential_integrity(con, section, contract))
    return CheckpointReport(section=section, checks=tuple(checks))
