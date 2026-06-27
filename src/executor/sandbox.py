"""Sandbox lifecycle (Phase 4).

A sandbox is an independent, writable copy of the canonical warehouse, placed in
its **own isolated directory outside the warehouse root**. Two guarantees follow:

1. The canonical can still be opened read-write for ingestion (the sandbox holds
   no handle on it).
2. Code running in the sandbox has **no path to the canonical** — the subprocess
   receives only the sandbox directory, and a ``..`` traversal from there lands in
   a temp area, never the warehouse. So a sandbox cannot write back to canonical.

The clone + all run outputs live under the sandbox dir and are accessible until
the sandbox is destroyed (explicit delete or session end).
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from warehouse import cow_copy_database
from warehouse.warehouse import DB_FILENAME

CLONE_FILENAME = "clone.duckdb"
OUTPUTS_DIRNAME = "outputs"


@dataclass(frozen=True)
class SandboxHandle:
    id: str
    dir: Path  # isolated, outside the warehouse root
    db_path: Path
    outputs_dir: Path


class SandboxManager:
    """Owns sandbox directories for a warehouse. Discards them on session end."""

    def __init__(self, root: str | Path, base_dir: str | Path | None = None) -> None:
        self.root = Path(root)
        # Sandboxes live OUTSIDE the warehouse root so user code can't traverse to
        # the canonical. Default to a dedicated dir under the system temp area.
        self.base_dir = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "annulus-sandboxes"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, SandboxHandle] = {}

    @property
    def canonical_path(self) -> Path:
        return self.root / DB_FILENAME

    def create(self) -> SandboxHandle:
        if not self.canonical_path.exists():
            raise FileNotFoundError(f"no canonical warehouse at {self.canonical_path}")
        sandbox_id = uuid.uuid4().hex
        sdir = self.base_dir / sandbox_id
        outputs = sdir / OUTPUTS_DIRNAME
        outputs.mkdir(parents=True, exist_ok=True)
        db_path = sdir / CLONE_FILENAME
        cow_copy_database(self.canonical_path, db_path)
        handle = SandboxHandle(id=sandbox_id, dir=sdir, db_path=db_path, outputs_dir=outputs)
        self._active[sandbox_id] = handle
        return handle

    def get(self, sandbox_id: str) -> SandboxHandle | None:
        return self._active.get(sandbox_id)

    def require(self, sandbox_id: str) -> SandboxHandle:
        handle = self._active.get(sandbox_id)
        if handle is None:
            raise KeyError(sandbox_id)
        return handle

    def delete(self, sandbox_id: str) -> bool:
        handle = self._active.pop(sandbox_id, None)
        if handle is None:
            return False
        shutil.rmtree(handle.dir, ignore_errors=True)
        return True

    def destroy_all(self) -> None:
        for sandbox_id in list(self._active):
            self.delete(sandbox_id)

    @property
    def active(self) -> tuple[SandboxHandle, ...]:
        return tuple(self._active.values())
