"""Phase 8.2 — adversarial pass on the complete system (through the REST API).

Priority attacks: SQL injection via agent chat, chart requests that try to pull
full tables, sandbox escape to the canonical DB, re-ingestion mutating prior
data, and biopack activating without explicit opt-in.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from agentic.steps import Answer, RunSql, StepDecision
from api.rest import create_app
from warehouse import sha256_file

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
)


class _Brain:
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


def _client(tmp_path, steps=None):
    return TestClient(create_app(tmp_path / "wh", brain_factory=lambda: _Brain(steps)))


def _ingest(client, name="orders.csv", content=ORDERS, engine="deterministic", biopack=None):
    data = {"engine": engine}
    if biopack:
        data["biopack"] = json.dumps(biopack)
    return client.post("/ingest", files={"file": (name, content, "text/csv")}, data=data)


def _canonical(tmp_path) -> Path:
    return tmp_path / "wh" / "warehouse.duckdb"


def test_sql_injection_via_agent_chat_is_blocked(tmp_path):
    base = _client(tmp_path)
    _ingest(base)
    section = base.get("/schema").json()["data"]["datasets"][0]["name"]
    before = sha256_file(_canonical(tmp_path))

    # The agent emits a DML "query"; the query service must reject it.
    steps = [RunSql(kind="run_sql", sql=f'DELETE FROM "{section}".raw')]
    client = _client(tmp_path, steps)
    events = [
        json.loads(l)
        for l in client.post("/agent/chat", json={"message": "wipe it", "history": []}).text.splitlines()
        if l.strip()
    ]
    sql_step = next(e for e in events if e["type"] == "step" and e["tool"] == "run_sql")
    assert "ERROR" in (sql_step["summary"] or "")  # rejected by the query service
    assert sha256_file(_canonical(tmp_path)) == before  # canonical untouched


def test_chart_request_cannot_pull_full_table(tmp_path):
    client = _client(tmp_path)
    # 12,000-row dataset; a scatter must be capped at 10,000 points.
    rows = "\n".join(f"{i},{i % 7}" for i in range(12_000))
    _ingest(client, name="big.csv", content="x,y\n" + rows + "\n")
    section = client.get("/schema").json()["data"]["datasets"][0]["name"]
    data = client.post(
        "/visualize",
        json={"type": "scatter", "section": section, "table": "raw", "x": "x", "y": "y"},
    ).json()["data"]
    assert data["row_count"] <= 10_000
    assert data["truncated"] is True


def test_sandbox_cannot_reach_canonical(tmp_path):
    client = _client(tmp_path)
    _ingest(client)
    before = sha256_file(_canonical(tmp_path))
    sid = client.post("/sandboxes").json()["data"]["sandbox_id"]
    # A script that tries to find and corrupt any nearby warehouse.
    code = (
        "import os, glob\n"
        "hits = glob.glob(os.path.join(os.path.dirname(db_path), '..', '**', 'warehouse.duckdb'), recursive=True)\n"
        "print('FOUND', len(hits))\n"
        "con.execute('CREATE TABLE wreck AS SELECT 1')\n"
    )
    run = client.post(f"/sandboxes/{sid}/run", json={"kind": "script", "code": code}).json()["data"]
    assert run["ok"] is True
    assert "FOUND 0" in run["stdout"]  # no canonical reachable from the sandbox
    assert sha256_file(_canonical(tmp_path)) == before


def test_reingestion_does_not_mutate_prior_data(tmp_path):
    client = _client(tmp_path)
    first = _ingest(client).json()["data"]["section"]
    rows_before = client.post(
        "/query", json={"sql": f'SELECT * FROM "{first}".raw ORDER BY order_id'}
    ).json()["data"]["rows"]

    second = _ingest(client).json()["data"]["section"]
    assert second != first

    rows_after = client.post(
        "/query", json={"sql": f'SELECT * FROM "{first}".raw ORDER BY order_id'}
    ).json()["data"]["rows"]
    assert rows_before == rows_after
    assert client.get("/schema").json()["data"]["dataset_count"] == 2


def test_biopack_never_activates_without_opt_in(tmp_path):
    client = _client(tmp_path)
    # A column literally named like SMILES — must still be stored verbatim.
    csv = "compound_id,smiles\n1,C1=CC=CC=C1\n2,CCO\n"
    _ingest(client, name="cmp.csv", content=csv)  # no biopack field
    section = client.get("/schema").json()["data"]["datasets"][0]["name"]
    cols = client.get(f"/schema/{section}").json()["data"]["tables"]
    fact = next(t for t in cols if t["name"] == "fact")
    names = {c["name"] for c in fact["columns"]}
    assert "smiles" in names
    assert "smiles_raw" not in names  # no biopack rename
    # Value stored exactly as the source (benzene NOT canonicalized).
    val = client.post(
        "/query", json={"sql": f"SELECT smiles FROM \"{section}\".raw WHERE compound_id='1'"}
    ).json()["data"]["rows"][0][0]
    assert val == "C1=CC=CC=C1"
