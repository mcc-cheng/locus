from __future__ import annotations

import pytest

from ingest import DeterministicIngestor
from warehouse import Warehouse, mutate, sha256_file

CSV = "id,grp,score\n1,A,10\n2,A,20\n3,B,30\n4,B,40\n5,B,50\n"


@pytest.fixture
def section(tmp_path, ts):
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    p = tmp_path / "d.csv"
    p.write_text(CSV, encoding="utf-8")
    sec = DeterministicIngestor(wh).ingest(p, ts).section
    wh.close()
    return root, sec


def _open(root):
    return Warehouse.open(root, verify_sources=False)


def test_delete_where_removes_matching_rows(section):
    root, sec = section
    wh = _open(root)
    try:
        n = mutate.delete_where(wh.con, sec, "raw", '"grp" = \'B\'')
        assert n == 3
        remaining = wh.con.execute(f'SELECT COUNT(*) FROM "{sec}"."raw"').fetchone()[0]
        assert remaining == 2
    finally:
        wh.close()


def test_update_where_changes_values(section):
    root, sec = section
    wh = _open(root)
    try:
        n = mutate.update_where(wh.con, sec, "raw", "grp", "Z", '"grp" = \'A\'')
        assert n == 2
        zs = wh.con.execute(f'SELECT COUNT(*) FROM "{sec}"."raw" WHERE "grp" = \'Z\'').fetchone()[0]
        assert zs == 2
    finally:
        wh.close()


def test_update_value_is_parameter_bound_not_interpolated(section):
    # A value containing SQL-ish text is stored verbatim, never executed.
    root, sec = section
    wh = _open(root)
    try:
        mutate.update_where(wh.con, sec, "raw", "grp", "'); DROP TABLE x; --", '"id" = \'1\'')
        val = wh.con.execute(f'SELECT "grp" FROM "{sec}"."raw" WHERE "id" = \'1\'').fetchone()[0]
        assert val == "'); DROP TABLE x; --"
    finally:
        wh.close()


def test_where_rejects_statement_chaining(section):
    root, sec = section
    wh = _open(root)
    try:
        with pytest.raises(ValueError):
            mutate.delete_where(wh.con, sec, "raw", "1=1; DROP TABLE foo")
    finally:
        wh.close()


def test_add_drop_rename_column(section):
    root, sec = section
    wh = _open(root)
    try:
        mutate.add_column(wh.con, sec, "raw", "note")
        assert "note" in mutate.columns(wh.con, sec)
        mutate.rename_column(wh.con, sec, "raw", "note", "comment")
        assert "comment" in mutate.columns(wh.con, sec) and "note" not in mutate.columns(wh.con, sec)
        mutate.drop_column(wh.con, sec, "raw", "comment")
        assert "comment" not in mutate.columns(wh.con, sec)
    finally:
        wh.close()


def test_drop_missing_column_raises(section):
    root, sec = section
    wh = _open(root)
    try:
        with pytest.raises(ValueError):
            mutate.drop_column(wh.con, sec, "raw", "does_not_exist")
    finally:
        wh.close()


def test_mutations_never_touch_preserved_source(section):
    # The whole point: edits change the working table but the original upload
    # remains byte-for-byte recoverable.
    root, sec = section
    wh = _open(root)
    src = wh.source_path(sec)
    before = sha256_file(src)
    try:
        mutate.delete_where(wh.con, sec, "raw", None)  # delete ALL rows
        assert wh.con.execute(f'SELECT COUNT(*) FROM "{sec}"."raw"').fetchone()[0] == 0
    finally:
        wh.close()
    assert sha256_file(src) == before, "preserved source must be untouched"
