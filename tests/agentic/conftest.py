from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentic.steps import Answer, StepDecision
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
    """Scripts a fixed sequence of tool steps, then answers with canned text."""

    def __init__(self, steps=None, *, answer="Here is the answer.", available=True):
        self._steps = list(steps or [])
        self._i = 0
        self._answer = answer
        self._available = available

    def ensure_available(self):
        if not self._available:
            from ingest.errors import OllamaUnavailableError

            raise OllamaUnavailableError("ollama down (test)")

    def decide_step(self, system, messages):
        if self._i < len(self._steps):
            step = self._steps[self._i]
            self._i += 1
            return StepDecision(thought="", step=step)
        return StepDecision(thought="", step=Answer(kind="answer"))

    def stream_answer(self, system, messages):
        for word in self._answer.split(" "):
            yield word + " "
