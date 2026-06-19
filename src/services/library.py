"""A tiny file-based store for things the user saves in the app:

  * **charts** — a saved visualization (Vega-Lite spec + metadata) the user can
    revisit and download later.
  * **chats** — past analyst conversations, so the user can reopen them.

Everything lives as JSON under ``<root>/library/`` — small, local, and easy to
inspect. The API layer holds the warehouse lock around these calls, so plain
read/replace file writes are sufficient (no extra locking here).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _dir(root: str | Path) -> Path:
    d = Path(root) / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(root: str | Path, name: str) -> Path:
    return _dir(root) / name


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(path: Path, items: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- charts -----------------------------------------------------------------


def list_charts(root: str | Path) -> list[dict]:
    """Saved charts, newest first."""
    return sorted(_load(_path(root, "charts.json")), key=lambda c: c.get("created", ""), reverse=True)


def save_chart(root: str | Path, chart: dict) -> dict:
    """Persist a chart. Requires at least ``spec``; stamps id/created."""
    if not chart.get("spec"):
        raise ValueError("a chart needs a 'spec'")
    path = _path(root, "charts.json")
    items = _load(path)
    record = {
        "id": chart.get("id") or uuid.uuid4().hex,
        "title": (chart.get("title") or "Untitled chart").strip(),
        "section": chart.get("section"),
        "spec": chart["spec"],
        "chart_request": chart.get("chart_request"),
        "created": _now(),
    }
    items.append(record)
    _save(path, items)
    return record


def delete_chart(root: str | Path, chart_id: str) -> bool:
    path = _path(root, "charts.json")
    items = _load(path)
    kept = [c for c in items if c.get("id") != chart_id]
    if len(kept) == len(items):
        return False
    _save(path, kept)
    return True


# ---- chats ------------------------------------------------------------------


def _chat_summary(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "title": c.get("title") or "New chat",
        "section": c.get("section"),
        "updated": c.get("updated") or c.get("created"),
    }


def list_chats(root: str | Path) -> list[dict]:
    """Lightweight summaries (no message bodies), most-recently-updated first."""
    chats = _load(_path(root, "chats.json"))
    chats.sort(key=lambda c: c.get("updated") or c.get("created") or "", reverse=True)
    return [_chat_summary(c) for c in chats]


def get_chat(root: str | Path, chat_id: str) -> dict | None:
    for c in _load(_path(root, "chats.json")):
        if c.get("id") == chat_id:
            return c
    return None


def save_chat(root: str | Path, chat: dict) -> dict:
    """Upsert a conversation by id (the client owns the id so it can grow a chat
    across turns). Empty conversations are not persisted."""
    messages: list[Any] = chat.get("messages") or []
    chat_id = chat.get("id") or uuid.uuid4().hex
    path = _path(root, "chats.json")
    items = _load(path)
    existing = next((c for c in items if c.get("id") == chat_id), None)
    record = {
        "id": chat_id,
        "title": (chat.get("title") or "New chat").strip()[:80],
        "section": chat.get("section"),
        "messages": messages,
        "created": (existing or {}).get("created") or _now(),
        "updated": _now(),
    }
    items = [c for c in items if c.get("id") != chat_id]
    items.append(record)
    _save(path, items)
    return record


def delete_chat(root: str | Path, chat_id: str) -> bool:
    path = _path(root, "chats.json")
    items = _load(path)
    kept = [c for c in items if c.get("id") != chat_id]
    if len(kept) == len(items):
        return False
    _save(path, kept)
    return True
