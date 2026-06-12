"""Phase 8.1 — end-to-end integration + cross-layer contract checks.

Drives the whole stack through the REST API and verifies the contracts the
frontend depends on: envelope shapes, response keys matching the TypeScript
interfaces, server-only chart aggregation, and that a chart built by the agent
matches one built directly by the visualization service.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic.steps import Answer, StepDecision
from api.rest import create_app

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
    "4,P3,Gizmo,Gadgets,2\n"
)


class _Brain:
    """Scripts a sequence of tool steps, then streams a canned answer."""

    def __init__(self, steps=None, answer="Done."):
        self._steps = list(steps or [])
        self._i = 0
        self._answer = answer

    def ensure_available(self):
        pass

    def decide_step(self, system, messages):
        if self._i < len(self._steps):
            s = self._steps[self._i]
            self._i += 1
            return StepDecision(step=s)
        return StepDecision(step=Answer(kind="answer"))

    def stream_answer(self, system, messages):
        yield self._answer


def _client(tmp_path, steps=None, answer="Done."):
    return TestClient(
        create_app(tmp_path / "wh", brain_factory=lambda: _Brain(steps, answer))
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

    # Agent builds the same chart via a make_chart tool step.
    from agentic.steps import MakeChart

    steps = [MakeChart(kind="make_chart", chart_type="bar", section=section, table="raw", x="category")]
    agent_client = _client(tmp_path, steps)
    events = [
        __import__("json").loads(line)
        for line in agent_client.post(
            "/agent/chat", json={"message": "bar of category", "history": []}
        ).text.splitlines()
        if line.strip()
    ]
    chart_ev = next(e for e in events if e["type"] == "chart")
    # Same encoding/mark — the agent goes through the same server aggregation.
    assert chart_ev["spec"]["mark"] == ui["spec"]["mark"]
    assert chart_ev["spec"]["encoding"] == ui["spec"]["encoding"]
    assert chart_ev["chart_request"]["section"] == section


def test_agent_chat_event_shapes(tmp_path):
    # The streamed events carry exactly the fields the UI reads.
    from agentic.steps import RunSql

    base = _client(tmp_path)
    _ingest(base)
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]
    steps = [RunSql(kind="run_sql", sql=f'SELECT 1 AS one FROM "{section}".raw')]
    client = _client(tmp_path, steps, answer="42")
    events = [
        __import__("json").loads(line)
        for line in client.post("/agent/chat", json={"message": "x", "history": []}).text.splitlines()
        if line.strip()
    ]
    kinds = {e["type"] for e in events}
    assert {"step", "token", "final"} <= kinds
    step = next(e for e in events if e["type"] == "step")
    assert set(step) >= {"type", "tool", "sql", "summary"}
    final = next(e for e in events if e["type"] == "final")
    assert "response" in final
