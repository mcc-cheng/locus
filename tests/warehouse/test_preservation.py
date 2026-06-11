from __future__ import annotations

import os
import stat

import pytest

from warehouse import SourceIntegrityError, Warehouse, sha256_file

CSV = "id,val\n1,a\n2,b\n"


def test_source_copied_verbatim_with_hash(warehouse, write_csv, ts):
    path = write_csv("data.csv", CSV)
    original_hash = sha256_file(path)
    man = warehouse.land_csv(path, ts)

    # Hash recorded on the manifest and equals the original file's hash.
    assert man.sha256 == original_hash

    # A byte-exact copy lives under source/<section>/<filename>.
    dest = warehouse.source_path(man.name)
    assert dest.exists()
    assert dest.read_bytes() == path.read_bytes()
    assert sha256_file(dest) == original_hash


def test_preserved_copy_is_read_only(warehouse, write_csv, ts):
    path = write_csv("data.csv", CSV)
    man = warehouse.land_csv(path, ts)
    dest = warehouse.source_path(man.name)
    mode = dest.stat().st_mode
    assert not (mode & stat.S_IWUSR), "preserved source should not be writable"


def test_copy_happens_before_and_independent_of_original(warehouse, write_csv, ts):
    path = write_csv("data.csv", CSV)
    man = warehouse.land_csv(path, ts)
    dest = warehouse.source_path(man.name)
    # Mutate the user's original after ingestion; the preserved copy is untouched.
    path.write_text("totally different\n", encoding="utf-8")
    assert dest.read_bytes() != path.read_bytes()
    assert sha256_file(dest) == man.sha256


def test_verify_sources_passes_when_intact(warehouse, write_csv, ts):
    warehouse.land_csv(write_csv("a.csv", CSV), ts)
    warehouse.land_csv(write_csv("b.csv", "x\n1\n"), ts)
    results = warehouse.verify_sources()
    assert len(results) == 2
    assert all(r.passed for r in results)


def test_open_raises_on_tampered_source(warehouse, write_csv, ts):
    man = warehouse.land_csv(write_csv("a.csv", CSV), ts)
    root = warehouse.root
    warehouse.close()

    # Tamper with the preserved copy (make writable, then overwrite).
    dest = root / "source" / man.name / "a.csv"
    os.chmod(dest, stat.S_IWUSR | stat.S_IRUSR)
    dest.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(SourceIntegrityError):
        Warehouse.open(root)

    # With verification disabled, recovery tooling can still open it.
    wh = Warehouse.open(root, verify_sources=False)
    wh.close()


def test_open_raises_on_missing_source(warehouse, write_csv, ts):
    man = warehouse.land_csv(write_csv("a.csv", CSV), ts)
    root = warehouse.root
    warehouse.close()

    dest = root / "source" / man.name / "a.csv"
    os.chmod(dest, stat.S_IWUSR | stat.S_IRUSR)
    dest.unlink()

    with pytest.raises(SourceIntegrityError):
        Warehouse.open(root)


def test_rejected_ingest_leaves_no_source(warehouse, write_csv, ts, monkeypatch):
    from warehouse import models
    import warehouse.warehouse as wh_mod

    def fail(con, section, csv_path, options, table="raw"):
        return models.CheckpointReport(
            section=section,
            checks=(models.CheckResult(name="row_count_roundtrip", passed=False),),
        )

    monkeypatch.setattr(wh_mod, "run_landing_checkpoint", fail)
    path = write_csv("bad.csv", CSV)
    with pytest.raises(Exception):
        warehouse.land_csv(path, ts)

    # No staged source dir left behind.
    leftover = list((warehouse.source_dir).glob("bad__*"))
    assert leftover == []
