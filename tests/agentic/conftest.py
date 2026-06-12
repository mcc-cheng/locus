from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import DeterministicIngestor
from warehouse import Warehouse

ASSAY = (
    "id,dose,response,grp\n"
    "1,0.1,5,A\n"
    "2,1.0,12,A\n"
    "3,10,30,A\n"
    "4,0.1,4,B\n"
    "5,1.0,9,B\n"
    "6,10,26,B\n"
)


@pytest.fixture
def agent_root(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    p = tmp_path / "assay.csv"
    p.write_text(ASSAY, encoding="utf-8")
    res = DeterministicIngestor(wh).ingest(p, datetime(2026, 6, 11, tzinfo=timezone.utc))
    section = res.section
    wh.close()
    return root, section


class FakeBrain:
    """Returns a canned AgentDecision."""

    def __init__(self, decision):
        self._decision = decision

    def decide(self, system: str, user: str):
        return self._decision
