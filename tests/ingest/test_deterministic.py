from __future__ import annotations

import pytest

from ingest import DeterministicIngestor, IngestRejected, read_contract

# order_id is a clean unique PK; product_id is a repeating key that functionally
# determines product_name and category -> one dimension extracted.
ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
    "4,P3,Gizmo,Gadgets,2\n"
)

# A flat table with no repeating key -> single fact, no dimensions.
FLAT = "a,b\n1,2\n3,4\n5,6\n"


def _ingest(warehouse, write_csv, ts, name, content):
    return DeterministicIngestor(warehouse).ingest(write_csv(name, content), ts)


def test_builds_star_schema(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    c = res.contract
    assert c.fact_table == "fact"
    table_names = {t.name for t in c.tables}
    assert table_names == {"fact", "dim_product_id"}
    fact = c.table("fact")
    assert fact.primary_key == ("order_id",)
    assert set(fact.columns) == {"order_id", "product_id", "qty"}
    dim = c.table("dim_product_id")
    assert dim.primary_key == ("product_id",)
    assert set(dim.columns) == {"product_id", "product_name", "category"}
    assert len(c.foreign_keys) == 1
    fk = c.foreign_keys[0]
    assert (fk.table, fk.columns, fk.ref_table) == ("fact", ("product_id",), "dim_product_id")


def test_all_five_qc_checks_pass(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    assert res.qc.passed
    names = {c.name for c in res.qc.checks}
    assert names == {
        "row_count_roundtrip",
        "zero_orphan_fks",
        "distinct_value_containment",
        "schema_contract_match",
        "referential_integrity",
    }


def test_dimension_is_deduplicated_verbatim(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    con = warehouse.con
    rows = con.execute(
        f'SELECT product_id, product_name, category FROM "{res.section}".dim_product_id '
        "ORDER BY product_id"
    ).fetchall()
    assert rows == [
        ("P1", "Widget", "Tools"),
        ("P2", "Gadget", "Tools"),
        ("P3", "Gizmo", "Gadgets"),
    ]


def test_fact_preserves_row_count(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    n = warehouse.con.execute(f'SELECT COUNT(*) FROM "{res.section}".fact').fetchone()[0]
    assert n == 4


def test_no_columns_fabricated(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    all_cols = {col for t in res.contract.tables for col in t.columns}
    assert all_cols == set(res.contract.source_columns)


def test_flat_table_yields_single_fact(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "flat.csv", FLAT)
    assert {t.name for t in res.contract.tables} == {"fact"}
    assert res.contract.foreign_keys == ()
    assert res.qc.passed


def test_artifacts_written_and_roundtrip(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    assert res.contract_path.exists()
    assert res.audit_path.exists()
    # Contract sidecar round-trips to an equal object.
    assert read_contract(res.contract_path) == res.contract


def test_contract_persisted_in_metadata(warehouse, write_csv, ts):
    res = _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    row = warehouse.con.execute(
        'SELECT engine, contract FROM "_locus".sections WHERE name = ?', [res.section]
    ).fetchone()
    assert row[0] == "deterministic"
    assert row[1] is not None and "dim_product_id" in row[1]


def test_qc_failure_rejects_and_rolls_back(warehouse, write_csv, ts, monkeypatch):
    """A real data-loss bug in assembly must be caught by QC and rejected."""
    import ingest.assembly as asm

    original = asm.build_relational

    def corrupt(con, section, contract):
        original(con, section, contract)
        # Silently drop a fact row -> row_count + reconstruction must fail.
        con.execute(f'DELETE FROM "{section}".fact WHERE order_id = \'1\'')

    monkeypatch.setattr(asm, "build_relational", corrupt)

    with pytest.raises(IngestRejected) as ei:
        _ingest(warehouse, write_csv, ts, "orders.csv", ORDERS)
    failed = {c.name for c in ei.value.report.failures}
    assert "referential_integrity" in failed

    # Nothing sealed; no section, no sidecar artifacts.
    assert warehouse.list_sections() == []
    assert not list((warehouse.root / "contracts").glob("*.json")) if (
        warehouse.root / "contracts"
    ).exists() else True
    leftover_sources = list(warehouse.source_dir.glob("orders__*"))
    assert leftover_sources == []
