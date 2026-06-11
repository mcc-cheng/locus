"""Adversarial tests for the Phase 1-2 non-destructive guarantees."""

from __future__ import annotations

from ingest import DeterministicIngestor

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
)


def _det(warehouse):
    return DeterministicIngestor(warehouse)


def test_reingestion_never_mutates_prior_data(warehouse, write_csv, ts):
    """Re-uploading the same file creates a new isolated section; the first is
    left byte-identical."""
    first = _det(warehouse).ingest(write_csv("orders.csv", ORDERS), ts)
    before = warehouse.con.execute(
        f'SELECT * FROM "{first.section}".fact ORDER BY order_id'
    ).fetchall()

    second = _det(warehouse).ingest(write_csv("orders.csv", ORDERS), ts)
    assert second.section != first.section

    after = warehouse.con.execute(
        f'SELECT * FROM "{first.section}".fact ORDER BY order_id'
    ).fetchall()
    assert before == after
    assert {m.name for m in warehouse.list_sections()} == {first.section, second.section}


def test_malicious_column_names_are_safe(warehouse, write_csv, ts):
    """Column names containing SQL metacharacters must not break or inject."""
    csv = "id,a; DROP TABLE t; --,o'brien\n1,x,y\n2,p,q\n"
    res = _det(warehouse).ingest(write_csv("evil.csv", csv), ts)
    assert res.qc.passed
    cols = set(res.contract.source_columns)
    assert "a; DROP TABLE t; --" in cols
    assert "o'brien" in cols
    # Data intact and the warehouse metadata table still exists (no injection).
    n = warehouse.con.execute(f'SELECT COUNT(*) FROM "{res.section}".fact').fetchone()[0]
    assert n == 2
    assert warehouse.con.execute('SELECT COUNT(*) FROM "_locus".sections').fetchone()[0] >= 1


def test_empty_table_ingests_losslessly(warehouse, write_csv, ts):
    res = _det(warehouse).ingest(write_csv("empty.csv", "a,b\n"), ts)
    assert res.qc.passed
    assert {t.name for t in res.contract.tables} == {"fact"}
    n = warehouse.con.execute(f'SELECT COUNT(*) FROM "{res.section}".fact').fetchone()[0]
    assert n == 0


def test_duplicate_rows_preserved_as_multiset(warehouse, write_csv, ts):
    csv = "k,v\nA,x\nA,x\nB,y\n"  # (A,x) appears twice
    res = _det(warehouse).ingest(write_csv("dups.csv", csv), ts)
    assert res.qc.passed
    rows = warehouse.con.execute(
        f'SELECT k, v FROM "{res.section}".fact ORDER BY k, v'
    ).fetchall()
    assert rows == [("A", "x"), ("A", "x"), ("B", "y")]  # duplicate retained


def test_value_with_newline_and_comma_preserved(warehouse, write_csv, ts):
    csv = 'id,note\n1,"line1\nline2"\n2,"a,b,c"\n'
    res = _det(warehouse).ingest(write_csv("multiline.csv", csv), ts)
    assert res.qc.passed
    note1 = warehouse.con.execute(
        f"SELECT note FROM \"{res.section}\".fact WHERE id = '1'"
    ).fetchone()[0]
    assert note1 == "line1\nline2"
