from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import DeterministicIngestor
from warehouse import Warehouse

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
    "4,P3,Gizmo,Gadgets,2\n"
)
PATIENTS = "patient_id,age,sex\nA,30,F\nB,40,M\n"


@pytest.fixture
def ts() -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sealed_root(tmp_path: Path, ts) -> Path:
    """A sealed warehouse with two ingested datasets; returns its root path."""
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    ing = DeterministicIngestor(wh)
    (tmp_path / "orders.csv").write_text(ORDERS, encoding="utf-8")
    (tmp_path / "patients.csv").write_text(PATIENTS, encoding="utf-8")
    ing.ingest(tmp_path / "orders.csv", ts)
    ing.ingest(tmp_path / "patients.csv", ts)
    wh.close()
    return root
