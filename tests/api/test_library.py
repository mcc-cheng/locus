from __future__ import annotations

from fastapi.testclient import TestClient

from api.rest import create_app

SPEC = {"mark": "bar", "data": {"values": [{"a": 1}]}}


def _client(tmp_path):
    return TestClient(create_app(tmp_path / "wh"))


def test_save_list_delete_chart(tmp_path):
    c = _client(tmp_path)
    assert c.get("/library/items").json()["data"] == []

    saved = c.post("/library/items", json={"kind": "chart", "title": "My chart", "spec": SPEC}).json()["data"]
    assert saved["id"] and saved["title"] == "My chart" and saved["kind"] == "chart"

    items = c.get("/library/items").json()["data"]
    assert len(items) == 1 and items[0]["spec"] == SPEC

    assert c.delete(f"/library/items/{saved['id']}").status_code == 200
    assert c.get("/library/items").json()["data"] == []
    assert c.delete(f"/library/items/{saved['id']}").status_code == 404


def test_save_figure(tmp_path):
    c = _client(tmp_path)
    img = "data:image/png;base64,iVBORw0KGgo="
    saved = c.post("/library/items", json={"kind": "figure", "title": "Fig 1", "image": img}).json()["data"]
    assert saved["kind"] == "figure" and saved["image"] == img


def test_item_requires_payload(tmp_path):
    c = _client(tmp_path)
    assert c.post("/library/items", json={"kind": "chart", "spec": {}}).status_code == 400
    assert c.post("/library/items", json={"kind": "figure"}).status_code == 400


def test_folders_and_move(tmp_path):
    c = _client(tmp_path)
    # saving into a nested folder registers the folder + ancestors
    it = c.post(
        "/library/items",
        json={"kind": "chart", "title": "T", "spec": SPEC, "folder": "Reports/Figures"},
    ).json()["data"]
    assert it["folder"] == "Reports/Figures"
    folders = c.get("/library/folders").json()["data"]
    assert "Reports" in folders and "Reports/Figures" in folders

    # explicit empty folder
    c.post("/library/folders", json={"path": "Scratch"})
    assert "Scratch" in c.get("/library/folders").json()["data"]

    # move the item to the root
    moved = c.patch(f"/library/items/{it['id']}", json={"folder": ""}).json()["data"]
    assert moved["folder"] == ""

    # deleting a folder reparents its items (none here) and removes the subtree
    assert c.delete("/library/folders", params={"path": "Reports"}).status_code == 200
    folders = c.get("/library/folders").json()["data"]
    assert "Reports" not in folders and "Reports/Figures" not in folders


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

    # rename updates the title but PRESERVES the messages (no accidental wipe)
    c.patch("/library/chats/abc", json={"title": "Renamed via PATCH"})
    assert c.get("/library/chats/abc").json()["data"]["messages"] == msgs
    assert c.get("/library/chats").json()["data"][0]["title"] == "Renamed via PATCH"
    assert c.patch("/library/chats/missing", json={"title": "x"}).status_code == 404

    assert c.delete("/library/chats/abc").status_code == 200
    assert c.get("/library/chats").json()["data"] == []
