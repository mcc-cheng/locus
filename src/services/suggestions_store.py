"""Per-section cache of agent-generated chart suggestions.

Written once, best-effort, after an ingest seals (see the ``/ingest`` handler);
read by ``GET /visualize/suggestions``. Absence is normal (e.g. Ollama was not
running at ingest) and means the endpoint falls back to deterministic
suggestions. Same atomic-write pattern as ``ingest/audit.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import ChartSuggestion


def _path(root: str | Path, section: str, table: str) -> Path:
    safe = f"{section}.{table}".replace("/", "_")
    return Path(root) / "suggestions" / f"{safe}.suggestions.json"


def write(root: str | Path, section: str, table: str, suggestions: list[ChartSuggestion]) -> Path:
    path = _path(root, section, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([s.model_dump() for s in suggestions], indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return path


def read(root: str | Path, section: str, table: str) -> list[ChartSuggestion] | None:
    path = _path(root, section, table)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [ChartSuggestion.model_validate(item) for item in raw]
    except Exception:
        return None  # corrupt cache -> behave as if absent
