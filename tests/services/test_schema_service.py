from __future__ import annotations

import duckdb
import pytest

from services import SchemaService
from warehouse import SectionNotFoundError


def test_list_datasets(sealed_root):
    with SchemaService.open(sealed_root) as svc:
        datasets = svc.list_datasets()
    names = {d.source_filename for d in datasets}
    assert names == {"orders.csv", "patients.csv"}


def test_get_dataset_structure(sealed_root):
    with SchemaService.open(sealed_root) as svc:
        orders = next(d for d in svc.list_datasets() if d.source_filename == "orders.csv")
        man = svc.get_dataset(orders.name)
    table_names = {t.name for t in man.tables}
    assert {"raw", "fact", "dim_product_id"} <= table_names
    raw = man.raw
    assert raw.row_count == 4
    assert all(c.stored_type.upper() == "VARCHAR" for c in raw.columns)
    assert man.sha256 is not None


def test_unknown_dataset_raises(sealed_root):
    with SchemaService.open(sealed_root) as svc:
        with pytest.raises(SectionNotFoundError):
            svc.get_dataset("does_not_exist")


def test_summary_aggregates(sealed_root):
    with SchemaService.open(sealed_root) as svc:
        summary = svc.summary()
    assert summary.dataset_count == 2
    assert summary.total_rows == 4 + 2  # orders + patients raw rows
    assert summary.total_source_bytes > 0
    for d in summary.datasets:
        assert d.engine == "deterministic"
        assert d.source_bytes > 0
        assert d.status == "sealed"


def test_service_is_read_only(sealed_root):
    with SchemaService.open(sealed_root) as svc:
        with pytest.raises(duckdb.Error):
            svc._db.con.execute('CREATE TABLE "_locus".x (a INT)')
