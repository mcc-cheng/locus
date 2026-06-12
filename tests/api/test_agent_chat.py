from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentic import AgentDecision, NarrativeAction, QueryAction
from api.rest import create_app

ORDERS = "order_id,product_id,qty\n1,P1,3\n2,P2,1\n3,P1,5\n"


def _client(tmp_path, decision):
    app = create_app(tmp_path / "wh", brain_factory=lambda: _FakeBrain(decision))
    return TestClient(app)


class _FakeBrain:
    def __init__(self, decision):
        self._decision = decision

    def decide(self, system, user):
        return self._decision


def _ingest(client):
    return client.post("/ingest", files={"file": ("orders.csv", ORDERS, "text/csv")})


def _read_stream(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_agent_chat_narrative(tmp_path):
    decision = AgentDecision(action=NarrativeAction(type="narrative", text="Two datasets loaded."))
    client = _client(tmp_path, decision)
    _ingest(client)
    resp = client.post("/agent/chat", json={"message": "hi", "history": []})
    assert resp.status_code == 200
    events = _read_stream(resp)
    kinds = [e["type"] for e in events]
    assert kinds == ["action", "result", "message"]
    assert events[0]["action_type"] == "narrative"
    assert events[-1]["response"] == "Two datasets loaded."


def test_agent_chat_query_streams_sql_and_result(tmp_path):
    client = TestClient(create_app(tmp_path / "wh", brain_factory=lambda: _Deferred()))
    _ingest(client)
    section = client.get("/schema").json()["data"]["datasets"][0]["name"]
    # Rebuild the client with a brain that queries that section.
    decision = AgentDecision(
        action=QueryAction(type="query", sql=f'SELECT count(*) AS n FROM "{section}".raw')
    )
    client = _client(tmp_path, decision)
    resp = client.post("/agent/chat", json={"message": "count rows", "history": []})
    events = {e["type"]: e for e in _read_stream(resp)}
    assert events["action"]["sql"] is not None
    assert events["result"]["result"]["rows"][0][0] == 3


class _Deferred:
    """A brain that should never be called (used only to bootstrap ingest)."""

    def decide(self, system, user):  # pragma: no cover
        raise AssertionError("should not be called")
