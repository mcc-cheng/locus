from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentic.steps import RunSql, StepDecision
from api.rest import create_app

ORDERS = "order_id,product_id,qty\n1,P1,3\n2,P2,1\n3,P1,5\n"


class _FakeBrain:
    """Runs one SQL step, then streams a canned answer."""

    def __init__(self, steps, answer):
        self._steps = list(steps)
        self._i = 0
        self._answer = answer

    def ensure_available(self):
        pass

    def decide_step(self, system, messages):
        from agentic.steps import Answer

        if self._i < len(self._steps):
            s = self._steps[self._i]
            self._i += 1
            return StepDecision(step=s)
        return StepDecision(step=Answer(kind="answer"))

    def stream_answer(self, system, messages):
        for w in self._answer.split(" "):
            yield w + " "


def _events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_agent_chat_streams_steps_tokens_and_final(tmp_path):
    # Ingest first with a plain app, then discover the section.
    base = TestClient(create_app(tmp_path / "wh"))
    base.post("/ingest", files={"file": ("orders.csv", ORDERS, "text/csv")})
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]

    steps = [RunSql(kind="run_sql", sql=f'SELECT count(*) AS n FROM "{section}".raw')]
    client = TestClient(
        create_app(tmp_path / "wh", brain_factory=lambda: _FakeBrain(steps, "There are 3 rows."))
    )
    resp = client.post("/agent/chat", json={"message": "count rows", "history": []})
    assert resp.status_code == 200
    events = _events(resp)
    kinds = [e["type"] for e in events]
    assert "step" in kinds and "token" in kinds and "final" in kinds

    step = next(e for e in events if e["type"] == "step")
    assert step["tool"] == "run_sql"
    assert step["sql"] is not None

    final = next(e for e in events if e["type"] == "final")
    assert final["response"].strip() == "There are 3 rows."


def test_confirmed_mutation_executes_deterministically(tmp_path):
    # A confirm payload runs the exact change WITHOUT invoking the model.
    base = TestClient(create_app(tmp_path / "wh"))
    base.post("/ingest", files={"file": ("orders.csv", ORDERS, "text/csv")})
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]

    def _no_llm():  # would explode if the model were (incorrectly) consulted
        raise AssertionError("model must not be called for a confirmed mutation")

    client = TestClient(create_app(tmp_path / "wh", brain_factory=_no_llm))
    action = {"op": "delete", "section": section, "table": "raw", "where": '"product_id" = \'P1\''}
    resp = client.post("/agent/chat", json={"message": "", "history": [], "confirm": action})
    assert resp.status_code == 200
    events = _events(resp)
    mutation = next(e for e in events if e["type"] == "mutation")
    assert mutation["rows_affected"] == 2  # two P1 rows
    # The row really is gone.
    total = base.get(f"/datasets/{section}/rows").json()["data"]["total"]
    assert total == 1


def test_confirmed_mutation_reports_errors(tmp_path):
    base = TestClient(create_app(tmp_path / "wh"))
    base.post("/ingest", files={"file": ("orders.csv", ORDERS, "text/csv")})
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]

    client = TestClient(create_app(tmp_path / "wh"))
    action = {"op": "drop_column", "section": section, "table": "raw", "column": "nope"}
    resp = client.post("/agent/chat", json={"message": "", "history": [], "confirm": action})
    events = _events(resp)
    assert any(e["type"] == "error" for e in events)
