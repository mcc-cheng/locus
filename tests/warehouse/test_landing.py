from __future__ import annotations

from datetime import datetime, timezone

import pytest

from warehouse import CheckpointError, SectionNotFoundError, Warehouse
from warehouse.checkpoints import quote_ident

# A CSV designed to break any engine that coerces types or "cleans" values.
VERBATIM_CSV = (
    "id,value,flag,sci,zip,note\n"
    "1,1.0,TRUE,1e3,00123,hello\n"
    "2,1.00,True,1E3,007,\n"
    "3,001,false,2.5e-1,42,\"a,b\"\n"
)


def _land(wh: Warehouse, write_csv, name: str, content: str, ts):
    path = write_csv(name, content)
    return wh.land_csv(path, ts)


def test_landing_creates_isolated_section(warehouse, write_csv, ts):
    man = _land(warehouse, write_csv, "sales.csv", VERBATIM_CSV, ts)
    assert man.name == "sales__20260611T120000Z"
    assert man.source_filename == "sales.csv"
    assert man.raw.row_count == 3
    assert [c.name for c in man.raw.columns] == ["id", "value", "flag", "sci", "zip", "note"]


def test_all_columns_stored_as_varchar(warehouse, write_csv, ts):
    man = _land(warehouse, write_csv, "sales.csv", VERBATIM_CSV, ts)
    assert all(c.stored_type.upper() == "VARCHAR" for c in man.raw.columns)


def test_values_stored_verbatim_no_coercion(warehouse, write_csv, ts):
    man = _land(warehouse, write_csv, "sales.csv", VERBATIM_CSV, ts)
    con = warehouse.con
    tbl = f'{quote_ident(man.name)}."raw"'
    rows = con.execute(f'SELECT value, flag, sci, zip FROM {tbl} ORDER BY id').fetchall()
    # Leading zeros, trailing-zero decimals, scientific notation, mixed-case
    # booleans all survive exactly as text.
    assert rows[0] == ("1.0", "TRUE", "1e3", "00123")
    assert rows[1] == ("1.00", "True", "1E3", "007")
    assert rows[2] == ("001", "false", "2.5e-1", "42")


def test_quoted_comma_value_preserved(warehouse, write_csv, ts):
    man = _land(warehouse, write_csv, "sales.csv", VERBATIM_CSV, ts)
    con = warehouse.con
    val = con.execute(
        f'SELECT note FROM {quote_ident(man.name)}."raw" WHERE id = \'3\''
    ).fetchone()[0]
    assert val == "a,b"


def test_two_datasets_are_isolated(warehouse, write_csv, ts):
    a = _land(warehouse, write_csv, "a.csv", "x\n1\n2\n", ts)
    b = _land(warehouse, write_csv, "b.csv", "y\n9\n", ts)
    names = {m.name for m in warehouse.list_sections()}
    assert a.name in names and b.name in names
    assert a.name != b.name
    # Each section only sees its own table/columns.
    assert [c.name for c in a.raw.columns] == ["x"]
    assert [c.name for c in b.raw.columns] == ["y"]


def test_drop_section_leaves_others_untouched(warehouse, write_csv, ts):
    a = _land(warehouse, write_csv, "a.csv", "x\n1\n", ts)
    b = _land(warehouse, write_csv, "b.csv", "y\n2\n", ts)
    warehouse.drop_section(a.name)
    remaining = {m.name for m in warehouse.list_sections()}
    assert remaining == {b.name}
    # The dropped schema is physically gone.
    schemas = [
        r[0]
        for r in warehouse.con.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()
    ]
    assert a.name not in schemas


def test_drop_unknown_section_raises(warehouse):
    with pytest.raises(SectionNotFoundError):
        warehouse.drop_section("does_not_exist")


def test_same_filename_same_timestamp_disambiguates(warehouse, write_csv, ts):
    a = _land(warehouse, write_csv, "dup.csv", "x\n1\n", ts)
    # Re-write same name with different content, same timestamp.
    b = _land(warehouse, write_csv, "dup.csv", "x\n2\n3\n", ts)
    assert a.name != b.name
    assert b.name == f"{a.name}_2"


def test_get_unknown_section_raises(warehouse):
    with pytest.raises(SectionNotFoundError):
        warehouse.get_section("nope")


def test_persistence_across_reopen(warehouse, write_csv, ts, tmp_path):
    man = _land(warehouse, write_csv, "sales.csv", VERBATIM_CSV, ts)
    root = warehouse.root
    warehouse.close()
    reopened = Warehouse.open(root)
    try:
        again = reopened.get_section(man.name)
        assert again.raw.row_count == 3
        assert again.source_filename == "sales.csv"
    finally:
        reopened.close()


def test_failed_checkpoint_rolls_back_and_raises(warehouse, write_csv, ts, monkeypatch):
    from warehouse import models
    import warehouse.warehouse as wh_mod

    def fake_checkpoint(con, section, csv_path, options, table="raw"):
        return models.CheckpointReport(
            section=section,
            checks=(
                models.CheckResult(name="row_count_roundtrip", passed=False, detail="forced"),
            ),
        )

    monkeypatch.setattr(wh_mod, "run_landing_checkpoint", fake_checkpoint)
    path = write_csv("bad.csv", "x\n1\n")
    with pytest.raises(CheckpointError):
        warehouse.land_csv(path, ts)

    # Nothing sealed, nothing visible, schema rolled back.
    assert warehouse.list_sections() == []
    schemas = [
        r[0]
        for r in warehouse.con.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()
    ]
    assert not any(s.startswith("bad__") for s in schemas)
