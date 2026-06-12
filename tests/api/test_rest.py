from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.rest import create_app

ORDERS = (
    "order_id,product_id,product_name,category,qty\n"
    "1,P1,Widget,Tools,3\n"
    "2,P2,Gadget,Tools,1\n"
    "3,P1,Widget,Tools,5\n"
    "4,P3,Gizmo,Gadgets,2\n"
)


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "wh")
    return TestClient(app)


def _ingest(client, name="orders.csv", content=ORDERS, engine="deterministic", biopack=None):
    data = {"engine": engine}
    if biopack is not None:
        data["biopack"] = biopack
    return client.post(
        "/ingest", files={"file": (name, content, "text/csv")}, data=data
    )


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "data": {"status": "ok"}, "error": None}


def test_health_deps_reports_ollama(client):
    body = client.get("/health/deps").json()
    assert body["ok"] is True
    assert body["data"]["ollama"]["status"] in {"ready", "unavailable"}


def test_ingest_then_schema_query_visualize(client):
    # ingest
    r = _ingest(client)
    assert r.status_code == 201, r.text
    section = r.json()["data"]["section"]
    assert r.json()["data"]["qc_passed"] is True

    # schema summary
    schema = client.get("/schema").json()
    assert schema["ok"] is True
    assert schema["data"]["dataset_count"] == 1
    assert schema["data"]["total_rows"] == 4

    # schema for one section
    one = client.get(f"/schema/{section}").json()
    table_names = {t["name"] for t in one["data"]["tables"]}
    assert {"raw", "fact"} <= table_names

    # query
    q = client.post(
        "/query", json={"sql": f'SELECT order_id FROM "{section}".raw ORDER BY order_id'}
    ).json()
    assert q["ok"] is True
    assert [row[0] for row in q["data"]["rows"]] == ["1", "2", "3", "4"]

    # visualize
    v = client.post(
        "/visualize",
        json={"type": "histogram", "section": section, "table": "raw", "x": "qty", "bins": 4},
    ).json()
    assert v["ok"] is True
    assert v["data"]["spec"]["mark"] == "bar"


def test_query_rejects_ddl_envelope(client):
    _ingest(client)
    r = client.post("/query", json={"sql": 'CREATE TABLE "_locus".x (a INT)'})
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False and body["error"]


def test_delete_dataset(client):
    r = _ingest(client)
    section = r.json()["data"]["section"]
    assert client.get("/schema").json()["data"]["dataset_count"] == 1

    deleted = client.delete(f"/schema/{section}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] == section

    # Gone from the warehouse and from disk.
    assert client.get("/schema").json()["data"]["dataset_count"] == 0
    assert client.get(f"/schema/{section}").status_code == 404


def test_delete_unknown_dataset_404(client):
    assert client.delete("/schema/does_not_exist").status_code == 404


def test_unknown_section_404(client):
    r = client.get("/schema/does_not_exist")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_unknown_engine_rejected(client):
    r = _ingest(client, engine="magic")
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_sandbox_lifecycle(client):
    _ingest(client)
    created = client.post("/sandboxes")
    assert created.status_code == 201
    sandbox_id = created.json()["data"]["sandbox_id"]

    deleted = client.delete(f"/sandboxes/{sandbox_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] == sandbox_id

    # deleting again -> 404
    assert client.delete(f"/sandboxes/{sandbox_id}").status_code == 404


def test_sandbox_run_script_and_results(client):
    _ingest(client)
    sid = client.post("/sandboxes").json()["data"]["sandbox_id"]

    run = client.post(
        f"/sandboxes/{sid}/run",
        json={"kind": "script", "code": "print('HELLO_SANDBOX'); con.execute('CREATE TABLE t AS SELECT 1')"},
    )
    assert run.status_code == 200, run.text
    body = run.json()["data"]
    assert body["ok"] is True
    assert "HELLO_SANDBOX" in body["stdout"]

    # results endpoint returns the latest run
    results = client.get(f"/sandboxes/{sid}/results").json()
    assert results["data"]["run_id"] == body["run_id"]

    client.delete(f"/sandboxes/{sid}")
    # results gone after delete
    assert client.get(f"/sandboxes/{sid}/results").status_code == 404


def test_sandbox_run_requires_code(client):
    _ingest(client)
    sid = client.post("/sandboxes").json()["data"]["sandbox_id"]
    r = client.post(f"/sandboxes/{sid}/run", json={"kind": "script"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_run_on_unknown_sandbox_404(client):
    r = client.post("/sandboxes/nope/run", json={"kind": "script", "code": "print(1)"})
    assert r.status_code == 404


def test_envelope_shape_is_consistent(client):
    # success and error responses both carry ok/data/error keys
    for resp in [client.get("/health"), client.get("/schema/nope")]:
        body = resp.json()
        assert set(body.keys()) == {"ok", "data", "error"}
