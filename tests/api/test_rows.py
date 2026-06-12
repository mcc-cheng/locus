from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.rest import create_app
from warehouse import sha256_file

CSV = "name,age\nAlice,30\nBob,40\nCarol,50\n"


@pytest.fixture
def client_section(tmp_path):
    client = TestClient(create_app(tmp_path / "wh"))
    client.post("/ingest", files={"file": ("people.csv", CSV, "text/csv")})
    section = client.get("/schema").json()["data"]["datasets"][0]["name"]
    return client, section, tmp_path


def test_read_rows_paginated(client_section):
    client, section, _ = client_section
    data = client.get(f"/datasets/{section}/rows?offset=0&limit=2").json()["data"]
    assert data["total"] == 3
    assert data["columns"] == ["name", "age"]
    assert len(data["rows"]) == 2
    assert data["rows"][0]["cells"] == ["Alice", "30"]
    assert isinstance(data["rows"][0]["rid"], int)


def test_add_update_delete_row(client_section):
    client, section, _ = client_section

    # add
    rid = client.post(f"/datasets/{section}/rows", json={"values": {"name": "Dave"}}).json()["data"]["rid"]
    assert client.get(f"/datasets/{section}/rows").json()["data"]["total"] == 4

    # update a cell
    client.patch(f"/datasets/{section}/rows/{rid}", json={"column": "age", "value": "60"})
    all_rows = client.get(f"/datasets/{section}/rows?limit=10").json()["data"]["rows"]
    dave = next(r for r in all_rows if r["rid"] == rid)
    assert dave["cells"] == ["Dave", "60"]

    # delete
    assert client.delete(f"/datasets/{section}/rows/{rid}").status_code == 200
    assert client.get(f"/datasets/{section}/rows").json()["data"]["total"] == 3


def test_delete_unknown_row_404(client_section):
    client, section, _ = client_section
    assert client.delete(f"/datasets/{section}/rows/99999").status_code == 404


def test_editing_never_touches_preserved_source(client_section):
    client, section, tmp_path = client_section
    src = tmp_path / "wh" / "source" / section / "people.csv"
    before = sha256_file(src)

    client.post(f"/datasets/{section}/rows", json={"values": {"name": "Zed", "age": "99"}})
    client.patch(f"/datasets/{section}/rows/0", json={"column": "name", "value": "ALICE"})

    # The original uploaded file is still byte-for-byte intact.
    assert sha256_file(src) == before
    assert src.read_text() == CSV
