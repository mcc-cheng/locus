from __future__ import annotations

from fastapi.testclient import TestClient

from api.rest import create_app

SPEC = {"mark": "bar", "data": {"values": [{"a": 1}]}}


def _client(tmp_path):
    return TestClient(create_app(tmp_path / "wh"))


def test_save_list_delete_chart(tmp_path):
    c = _client(tmp_path)
    assert c.get("/library/charts").json()["data"] == []

    saved = c.post("/library/charts", json={"title": "My chart", "spec": SPEC}).json()["data"]
    assert saved["id"] and saved["title"] == "My chart"

    charts = c.get("/library/charts").json()["data"]
    assert len(charts) == 1 and charts[0]["spec"] == SPEC

    assert c.delete(f"/library/charts/{saved['id']}").status_code == 200
    assert c.get("/library/charts").json()["data"] == []
    assert c.delete(f"/library/charts/{saved['id']}").status_code == 404


def test_chart_requires_spec(tmp_path):
    c = _client(tmp_path)
    # empty spec dict -> rejected
    assert c.post("/library/charts", json={"title": "x", "spec": {}}).status_code == 400


def test_chat_upsert_and_summary_hides_messages(tmp_path):
    c = _client(tmp_path)
    msgs = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]
    c.put("/library/chats/abc", json={"id": "abc", "title": "First", "section": "s1", "messages": msgs})

    # list is summaries only (no message bodies)
    listed = c.get("/library/chats").json()["data"]
    assert len(listed) == 1 and listed[0]["title"] == "First"
    assert "messages" not in listed[0]

    # full fetch includes messages
    full = c.get("/library/chats/abc").json()["data"]
    assert full["messages"] == msgs

    # upsert (same id) updates in place, doesn't duplicate
    c.put("/library/chats/abc", json={"id": "abc", "title": "Renamed", "messages": msgs})
    listed = c.get("/library/chats").json()["data"]
    assert len(listed) == 1 and listed[0]["title"] == "Renamed"

    assert c.delete("/library/chats/abc").status_code == 200
    assert c.get("/library/chats").json()["data"] == []
