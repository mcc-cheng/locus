from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from executor import SandboxLimits, SandboxManager, run_notebook, run_script
from ingest import DeterministicIngestor
from warehouse import Warehouse, sha256_file

ORDERS = "order_id,product_id,qty\n1,P1,3\n2,P2,1\n3,P1,5\n"


@pytest.fixture
def warehouse_root(tmp_path: Path) -> Path:
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    p = tmp_path / "orders.csv"
    p.write_text(ORDERS, encoding="utf-8")
    DeterministicIngestor(wh).ingest(p, datetime(2026, 6, 11, tzinfo=timezone.utc))
    wh.close()
    return root


@pytest.fixture
def manager(warehouse_root, tmp_path):
    mgr = SandboxManager(warehouse_root, base_dir=tmp_path / "sboxes")
    try:
        yield mgr
    finally:
        mgr.destroy_all()


def test_sandbox_dir_is_outside_warehouse_root(manager, warehouse_root):
    h = manager.create()
    assert warehouse_root not in h.dir.parents
    assert h.db_path.exists()


def test_script_reads_clone_data(manager):
    h = manager.create()
    res = run_script(
        h,
        "schema = con.execute(\"SELECT table_schema FROM information_schema.tables "
        "WHERE table_name='raw' AND table_schema NOT IN ('information_schema') LIMIT 1\").fetchone()[0]\n"
        "n = con.execute(f'SELECT count(*) FROM \"{schema}\".raw').fetchone()[0]\n"
        "print('RAWROWS', n)\n",
    )
    assert res.ok, res.stderr
    assert "RAWROWS 3" in res.stdout


def test_sandbox_write_does_not_touch_canonical(manager, warehouse_root):
    canonical = warehouse_root / "warehouse.duckdb"
    before = sha256_file(canonical)
    h = manager.create()
    res = run_script(
        h,
        "con.execute('CREATE TABLE scratch AS SELECT 1 AS x'); "
        "con.execute('INSERT INTO scratch VALUES (2)'); print('WROTE', "
        "con.execute('SELECT count(*) FROM scratch').fetchone()[0])",
    )
    assert res.ok, res.stderr
    assert "WROTE 2" in res.stdout
    # The clone changed; the canonical did not.
    assert sha256_file(canonical) == before


def test_network_is_blocked(manager):
    h = manager.create()
    res = run_script(
        h,
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "    print('NET_OK')\n"
        "except OSError:\n"
        "    print('NET_BLOCKED')\n",
    )
    assert "NET_BLOCKED" in res.stdout
    assert "NET_OK" not in res.stdout


def test_matplotlib_figure_saved_as_artifact(manager):
    h = manager.create()
    res = run_script(
        h, "import matplotlib.pyplot as plt\nplt.plot([1,2,3],[4,5,6])\nprint('PLOTTED')"
    )
    assert res.ok, res.stderr
    assert any(a.endswith(".png") for a in res.artifacts)


def test_sklearn_available(manager):
    h = manager.create()
    res = run_script(
        h,
        "from sklearn.linear_model import LinearRegression\n"
        "m = LinearRegression().fit([[0],[1],[2]], [0,1,2])\n"
        "print('COEF', round(float(m.coef_[0]), 3))",
    )
    assert res.ok, res.stderr
    assert "COEF 1.0" in res.stdout


def test_wall_clock_timeout(manager):
    h = manager.create()
    res = run_script(h, "while True:\n    pass", limits=SandboxLimits(timeout_s=1.0, cpu_seconds=5))
    assert res.timed_out is True
    assert res.ok is False


def test_user_error_is_captured(manager):
    h = manager.create()
    res = run_script(h, "raise ValueError('boom')")
    assert res.ok is False
    assert res.exit_code == 1
    assert "ValueError: boom" in res.stderr


def test_notebook_execution(manager):
    h = manager.create()
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": (
                    "import duckdb\n"
                    "c = duckdb.connect(db_path)\n"
                    "schema = c.execute(\"SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name='raw' AND table_schema NOT IN ('information_schema') LIMIT 1\").fetchone()[0]\n"
                    "print('NB_RAWROWS', c.execute(f'SELECT count(*) FROM \"{schema}\".raw').fetchone()[0])\n"
                ),
            }
        ],
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    res = run_notebook(h, nb)
    assert res.ok, res.stderr
    assert "executed.ipynb" in res.artifacts
    executed = (h.outputs_dir / res.run_id / "executed.ipynb").read_text()
    assert "NB_RAWROWS 3" in executed


def test_delete_removes_sandbox(manager):
    h = manager.create()
    assert h.dir.exists()
    assert manager.delete(h.id) is True
    assert not h.dir.exists()
    assert manager.delete(h.id) is False
