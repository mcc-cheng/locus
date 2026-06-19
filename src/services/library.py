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


# ---- saved items (charts + figures) -----------------------------------------
#
# A "saved item" is something the user kept while exploring: either a `chart`
# (a Vega-Lite spec they can re-render and download) or a `figure` (a matplotlib
# PNG the analyst produced, stored as a data URI). Items live in a virtual folder
# tree — `folder` is a path like "Reports/Figures" ("" means the root).


def _norm_folder(path: str | None) -> str:
    """Normalize a folder path: trim slashes/space, collapse empties. '' = root."""
    if not path:
        return ""
    parts = [p.strip() for p in str(path).split("/")]
    return "/".join(p for p in parts if p)


def _ancestors(path: str) -> list[str]:
    """All folder paths that must exist for `path` (incl. itself), excluding ''."""
    if not path:
        return []
    parts = path.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _items_path(root: str | Path) -> Path:
    return _path(root, "items.json")


def _load_items(root: str | Path) -> list[dict]:
    path = _items_path(root)
    items = _load(path)
    # One-time migration: fold any earlier charts.json into the unified store.
    legacy = _path(root, "charts.json")
    if not items and legacy.exists():
        for c in _load(legacy):
            items.append({**c, "kind": "chart", "folder": ""})
        if items:
            _save(path, items)
    return items


def list_items(root: str | Path) -> list[dict]:
    """All saved items, newest first."""
    return sorted(_load_items(root), key=lambda c: c.get("created", ""), reverse=True)


def save_item(root: str | Path, item: dict) -> dict:
    """Persist a chart or figure. Charts need a 'spec'; figures need an 'image'.
    Registers the (possibly new) folder so it shows up in the tree."""
    kind = item.get("kind") or "chart"
    if kind == "chart" and not item.get("spec"):
        raise ValueError("a chart needs a 'spec'")
    if kind == "figure" and not item.get("image"):
        raise ValueError("a figure needs an 'image'")
    folder = _norm_folder(item.get("folder"))
    record = {
        "id": item.get("id") or uuid.uuid4().hex,
        "kind": kind,
        "title": (item.get("title") or "Untitled").strip(),
        "folder": folder,
        "section": item.get("section"),
        "spec": item.get("spec"),
        "chart_request": item.get("chart_request"),
        "image": item.get("image"),
        "caption": item.get("caption"),
        "created": _now(),
    }
    items = _load_items(root)
    items.append(record)
    _save(_items_path(root), items)
    if folder:
        create_folder(root, folder)  # ensure the folder (and ancestors) exist
    return record


def delete_item(root: str | Path, item_id: str) -> bool:
    items = _load_items(root)
    kept = [c for c in items if c.get("id") != item_id]
    if len(kept) == len(items):
        return False
    _save(_items_path(root), kept)
    return True


def move_item(root: str | Path, item_id: str, folder: str | None) -> dict | None:
    """Move an item to another folder (creating it if new)."""
    folder = _norm_folder(folder)
    items = _load_items(root)
    found = None
    for it in items:
        if it.get("id") == item_id:
            it["folder"] = folder
            found = it
    if found is None:
        return None
    _save(_items_path(root), items)
    if folder:
        create_folder(root, folder)
    return found


# ---- folders ----------------------------------------------------------------


def list_folders(root: str | Path) -> list[str]:
    """Every folder path that exists, including ones implied by saved items."""
    folders = set(_load_folders(root))
    for it in _load_items(root):
        for anc in _ancestors(_norm_folder(it.get("folder"))):
            folders.add(anc)
    return sorted(folders)


def _load_folders(root: str | Path) -> list[str]:
    raw = _load(_path(root, "folders.json"))
    return [f for f in raw if isinstance(f, str)]


def create_folder(root: str | Path, path: str) -> list[str]:
    folder = _norm_folder(path)
    if not folder:
        raise ValueError("folder name is required")
    folders = set(_load_folders(root))
    folders.update(_ancestors(folder))
    ordered = sorted(folders)
    _save(_path(root, "folders.json"), ordered)
    return ordered


def delete_folder(root: str | Path, path: str) -> bool:
    """Remove a folder and its descendants. Items inside are moved to the root so
    nothing is silently lost."""
    folder = _norm_folder(path)
    if not folder:
        return False
    folders = _load_folders(root)
    prefix = folder + "/"
    kept = [f for f in folders if f != folder and not f.startswith(prefix)]
    changed = len(kept) != len(folders)
    _save(_path(root, "folders.json"), sorted(set(kept)))
    # Reparent any items in the removed subtree to the root.
    items = _load_items(root)
    moved = False
    for it in items:
        f = _norm_folder(it.get("folder"))
        if f == folder or f.startswith(prefix):
            it["folder"] = ""
            moved = True
    if moved:
        _save(_items_path(root), items)
    return changed or moved


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


def rename_chat(root: str | Path, chat_id: str, title: str) -> dict | None:
    """Update only a chat's title, preserving its messages (a safe rename that
    never risks wiping the conversation the way a full upsert could)."""
    path = _path(root, "chats.json")
    items = _load(path)
    found = None
    for c in items:
        if c.get("id") == chat_id:
            c["title"] = (title or "New chat").strip()[:80]
            c["updated"] = _now()
            found = c
    if found is None:
        return None
    _save(path, items)
    return _chat_summary(found)


def delete_chat(root: str | Path, chat_id: str) -> bool:
    path = _path(root, "chats.json")
    items = _load(path)
    kept = [c for c in items if c.get("id") != chat_id]
    if len(kept) == len(items):
        return False
    _save(path, kept)
    return True
