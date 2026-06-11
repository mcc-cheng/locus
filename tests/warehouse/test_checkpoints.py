from __future__ import annotations

from warehouse.checkpoints import quote_ident, run_landing_checkpoint
from warehouse.csv_source import CsvReadOptions

CSV = "id,val\n1,a\n2,b\n3,c\n"


def _land(warehouse, write_csv, ts):
    path = write_csv("d.csv", CSV)
    man = warehouse.land_csv(path, ts)
    return man, str(path)


def test_clean_landing_passes_checkpoint(warehouse, write_csv, ts):
    man, path = _land(warehouse, write_csv, ts)
    report = run_landing_checkpoint(warehouse.con, man.name, path, CsvReadOptions())
    assert report.passed
    assert {c.name for c in report.checks} >= {"row_count_roundtrip", "distinct_value_containment"}


def test_row_count_drift_is_caught(warehouse, write_csv, ts):
    man, path = _land(warehouse, write_csv, ts)
    # Simulate storage-layer row loss.
    warehouse.con.execute(f'DELETE FROM {quote_ident(man.name)}."raw" WHERE id = \'2\'')
    report = run_landing_checkpoint(warehouse.con, man.name, path, CsvReadOptions())
    assert not report.passed
    rc = next(c for c in report.checks if c.name == "row_count_roundtrip")
    assert not rc.passed
    assert rc.expected == "3" and rc.actual == "2"


def test_collapsed_distinct_values_are_caught(warehouse, write_csv, ts):
    # Two distinct source values collapsed into one. Row count is unchanged and
    # stored ⊆ source still holds, so only the reverse direction catches it.
    csv = "id,val\n1,1.0\n2,1.00\n"
    path = write_csv("collapse.csv", csv)
    man = warehouse.land_csv(path, ts)
    warehouse.con.execute(f'UPDATE {quote_ident(man.name)}."raw" SET val = \'1\'')
    report = run_landing_checkpoint(warehouse.con, man.name, str(path), CsvReadOptions())
    assert not report.passed
    failed = [c for c in report.failures if c.name == "distinct_value_containment"]
    assert any(c.column == "val" for c in failed)


def test_fabricated_value_is_caught(warehouse, write_csv, ts):
    man, path = _land(warehouse, write_csv, ts)
    # Simulate a coercion that invents a value not present in the source.
    warehouse.con.execute(
        f'UPDATE {quote_ident(man.name)}."raw" SET val = \'FABRICATED\' WHERE id = \'1\''
    )
    report = run_landing_checkpoint(warehouse.con, man.name, path, CsvReadOptions())
    assert not report.passed
    failed = [c for c in report.failures if c.name == "distinct_value_containment"]
    assert any(c.column == "val" for c in failed)
