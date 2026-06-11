from __future__ import annotations

import duckdb
import pytest

from warehouse import CanonicalDB, CloneManager, Warehouse, sha256_file

CSV = "id,val\n1,a\n2,b\n3,c\n"


@pytest.fixture
def sealed(tmp_path, write_csv, ts):
    """A sealed warehouse with one section; returns (root, section_name)."""
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    man = wh.land_csv(write_csv("d.csv", CSV), ts)
    section = man.name
    wh.close()  # ingestion done; canonical sealed and not open read-write
    return root, section


# ---- CanonicalDB (read-only) -------------------------------------------------


def test_canonical_opens_read_only_and_reads(sealed):
    root, section = sealed
    with CanonicalDB.open(root) as db:
        n = db.con.execute(f'SELECT COUNT(*) FROM "{section}"."raw"').fetchone()[0]
        assert n == 3


def test_canonical_rejects_writes(sealed):
    root, section = sealed
    with CanonicalDB.open(root) as db:
        with pytest.raises(duckdb.Error):
            db.con.execute(f'DELETE FROM "{section}"."raw"')
        with pytest.raises(duckdb.Error):
            db.con.execute('CREATE TABLE "_locus".sneaky (x INT)')


def test_canonical_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        CanonicalDB.open(tmp_path / "nope")


# ---- Clones (copy-on-write) --------------------------------------------------


def test_clone_reads_canonical_data(sealed):
    root, section = sealed
    with CloneManager.for_warehouse(root) as mgr:
        clone = mgr.create()
        n = clone.con.execute(f"SELECT COUNT(*) FROM {clone.canonical_ref(section)}").fetchone()[0]
        assert n == 3


def test_clone_is_writable_in_its_own_db(sealed):
    root, section = sealed
    with CloneManager.for_warehouse(root) as mgr:
        clone = mgr.create()
        clone.con.execute(
            f"CREATE TABLE experiment AS SELECT * FROM {clone.canonical_ref(section)}"
        )
        clone.con.execute("INSERT INTO experiment VALUES ('99', 'z')")
        n = clone.con.execute("SELECT COUNT(*) FROM experiment").fetchone()[0]
        assert n == 4  # 3 from canonical + 1 inserted, all in the clone


def test_clone_cannot_write_canonical(sealed):
    root, section = sealed
    with CloneManager.for_warehouse(root) as mgr:
        clone = mgr.create()
        with pytest.raises(duckdb.Error):
            clone.con.execute(f"DELETE FROM {clone.canonical_ref(section)}")
        with pytest.raises(duckdb.Error):
            clone.con.execute(
                f"INSERT INTO {clone.canonical_ref(section)} VALUES ('x', 'y')"
            )


def test_canonical_bytes_unchanged_after_clone_writes(sealed):
    root, section = sealed
    canonical_file = root / "warehouse.duckdb"
    before = sha256_file(canonical_file)
    with CloneManager.for_warehouse(root) as mgr:
        clone = mgr.create()
        clone.con.execute(
            f"CREATE TABLE t AS SELECT * FROM {clone.canonical_ref(section)}"
        )
        clone.con.execute("INSERT INTO t VALUES ('99','z')")
    after = sha256_file(canonical_file)
    assert before == after


def test_clones_discarded_on_session_end(sealed):
    root, _ = sealed
    paths = []
    with CloneManager.for_warehouse(root) as mgr:
        for _ in range(3):
            paths.append(mgr.create().path)
        assert all(p.exists() for p in paths)
        assert len(mgr.active) == 3
    # Context exit == session end: every clone file is gone.
    assert not any(p.exists() for p in paths)


def test_explicit_discard_removes_one_clone(sealed):
    root, _ = sealed
    with CloneManager.for_warehouse(root) as mgr:
        a = mgr.create()
        b = mgr.create()
        mgr.discard(a)
        assert not a.path.exists()
        assert b.path.exists()
        assert len(mgr.active) == 1


def test_for_warehouse_sweeps_stale_clones(sealed):
    root, _ = sealed
    clones_dir = root / "clones"
    clones_dir.mkdir(exist_ok=True)
    stale = clones_dir / "orphan.duckdb"
    stale.write_text("junk")
    # A new session sweeps leftovers from a crashed prior session.
    mgr = CloneManager.for_warehouse(root)
    assert not stale.exists()
    mgr.discard_all()
