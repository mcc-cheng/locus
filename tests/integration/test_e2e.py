"""Phase 8.1 — end-to-end integration + cross-layer contract checks.

Drives the whole stack through the REST API and verifies the contracts the
frontend depends on: envelope shapes, response keys matching the TypeScript
interfaces, server-only chart aggregation, and that a chart built by the agent
matches one built directly by the visualization service.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic import AgentDecision, ChartAction, QueryAction
from api.rest import create_app

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
    "4,P3,Gizmo,Gadgets,2\n"
)


class _Brain:
    def __init__(self, decision):
        self._d = decision

    def decide(self, system, user):
        return self._d


def _client(tmp_path, decision=None):
    return TestClient(
        create_app(tmp_path / "wh", brain_factory=lambda: _Brain(decision))
    )


def _ingest(client, name="orders.csv", content=ORDERS, engine="deterministic"):
    return client.post("/ingest", files={"file": (name, content, "text/csv")}, data={"engine": engine})


def test_full_flow(tmp_path):
    client = _client(tmp_path)
    # 1. ingest
    ing = _ingest(client).json()["data"]
    section = ing["section"]
    assert ing["qc_passed"] is True

    # 2. schema
    summ = client.get("/schema").json()["data"]
    assert summ["dataset_count"] == 1

    # 3. query
    q = client.post("/query", json={"sql": f'SELECT count(*) n FROM "{section}".raw'}).json()["data"]
    assert q["rows"][0][0] == 4

    # 4. visualize
    v = client.post(
        "/visualize",
        json={"type": "histogram", "section": section, "table": "raw", "x": "qty", "bins": 4},
    ).json()["data"]
    assert v["spec"]["mark"] == "bar"

    # 5. sandbox round-trip
    sid = client.post("/sandboxes").json()["data"]["sandbox_id"]
    run = client.post(
        f"/sandboxes/{sid}/run", json={"kind": "script", "code": "print('SBX')"}
    ).json()["data"]
    assert "SBX" in run["stdout"]
    assert client.delete(f"/sandboxes/{sid}").status_code == 200


# ---- cross-layer contract: response keys match the TS interfaces ------------


def test_schema_summary_keys(tmp_path):
    client = _client(tmp_path)
    _ingest(client)
    data = client.get("/schema").json()["data"]
    assert set(data) == {"dataset_count", "total_rows", "total_source_bytes", "datasets"}
    assert set(data["datasets"][0]) == {
        "name", "source_filename", "upload_timestamp", "engine",
        "row_count", "table_count", "source_bytes", "sha256", "status",
    }


def test_query_result_keys(tmp_path):
    client = _client(tmp_path)
    _ingest(client)
    section = client.get("/schema").json()["data"]["datasets"][0]["name"]
    data = client.post("/query", json={"sql": f'SELECT 1 FROM "{section}".raw'}).json()["data"]
    assert set(data) == {"columns", "rows", "page", "page_size", "has_more", "execution_ms"}


def test_visualize_result_keys(tmp_path):
    client = _client(tmp_path)
    _ingest(client)
    section = client.get("/schema").json()["data"]["datasets"][0]["name"]
    data = client.post(
        "/visualize", json={"type": "bar", "section": section, "table": "raw", "x": "category"}
    ).json()["data"]
    assert set(data) == {"spec", "data", "row_count", "truncated", "execution_ms"}
    # Spec carries inline aggregated data (server-side), not a table reference.
    assert "values" in data["spec"]["data"]


def test_envelope_on_every_endpoint(tmp_path):
    client = _client(tmp_path)
    _ingest(client)
    for resp in [
        client.get("/health"),
        client.get("/schema"),
        client.post("/query", json={"sql": "SELECT 1"}),
        client.get("/schema/unknown"),
    ]:
        assert set(resp.json()) == {"ok", "data", "error"}


# ---- analysis-artifact consistency: agent chart == UI chart -----------------


def test_agent_chart_matches_ui_chart(tmp_path):
    # First ingest with a plain client.
    base = _client(tmp_path)
    _ingest(base)
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]

    # UI builds the chart directly.
    ui = base.post(
        "/visualize",
        json={"type": "bar", "section": section, "table": "raw", "x": "category"},
    ).json()["data"]

    # Agent builds the same chart via a ChartAction.
    decision = AgentDecision(
        action=ChartAction(type="chart", chart_type="bar", section=section, table="raw", x="category")
    )
    agent_client = _client(tmp_path, decision)
    events = [
        __import__("json").loads(line)
        for line in agent_client.post(
            "/agent/chat", json={"message": "bar of category", "history": []}
        ).text.splitlines()
        if line.strip()
    ]
    action_ev = next(e for e in events if e["type"] == "action")
    # Same encoding/mark — the agent goes through the same server aggregation.
    assert action_ev["spec"]["mark"] == ui["spec"]["mark"]
    assert action_ev["spec"]["encoding"] == ui["spec"]["encoding"]


def test_agent_query_action_shape_matches_frontend(tmp_path):
    # The streamed action event carries exactly the fields the UI reads.
    base = _client(tmp_path)
    _ingest(base)
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]
    decision = AgentDecision(
        action=QueryAction(type="query", sql=f'SELECT 1 FROM "{section}".raw')
    )
    client = _client(tmp_path, decision)
    events = [
        __import__("json").loads(line)
        for line in client.post("/agent/chat", json={"message": "x", "history": []}).text.splitlines()
        if line.strip()
    ]
    types = [e["type"] for e in events]
    assert types == ["action", "result", "message"]
    action = next(e for e in events if e["type"] == "action")
    assert set(action) >= {"type", "action_type", "sql", "spec", "chart_request"}
