from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from warehouse import Warehouse


@pytest.fixture
def warehouse(tmp_path: Path) -> Warehouse:
    wh = Warehouse.open(tmp_path / "wh")
    try:
        yield wh
    finally:
        wh.close()


@pytest.fixture
def write_csv(tmp_path: Path):
    """Return a helper that writes CSV text to a file and returns its path."""

    def _write(name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    return _write


@pytest.fixture
def ts() -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
