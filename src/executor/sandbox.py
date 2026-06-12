"""Sandbox clone management (Phase 3.4 foundation; runtime in Phase 4).

A sandbox is an independent, writable **file copy** of the canonical warehouse.
Because it is a separate file (not an attached read-only handle), the canonical
can still be opened read-write for ingestion while sandboxes exist, and a
sandbox can be freely written to without any path back to the canonical.

This module manages the lifecycle (create / list / delete / destroy-all). The
actual code execution runtime (resource-limited subprocess) is Phase 4.1.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from warehouse import cow_copy_database
from warehouse.warehouse import DB_FILENAME

SANDBOX_DIRNAME = "sandboxes"


@dataclass(frozen=True)
class SandboxHandle:
    id: str
    db_path: Path


class SandboxManager:
    """Owns sandbox clone files for a warehouse. Discards them on session end."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.dir = self.root / SANDBOX_DIRNAME
        self.dir.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, SandboxHandle] = {}

    @property
    def canonical_path(self) -> Path:
        return self.root / DB_FILENAME

    def create(self) -> SandboxHandle:
        """Create a fresh writable copy of the canonical warehouse."""
        if not self.canonical_path.exists():
            raise FileNotFoundError(f"no canonical warehouse at {self.canonical_path}")
        sandbox_id = uuid.uuid4().hex
        db_path = self.dir / f"{sandbox_id}.duckdb"
        cow_copy_database(self.canonical_path, db_path)
        handle = SandboxHandle(id=sandbox_id, db_path=db_path)
        self._active[sandbox_id] = handle
        return handle

    def get(self, sandbox_id: str) -> SandboxHandle | None:
        return self._active.get(sandbox_id)

    def delete(self, sandbox_id: str) -> bool:
        handle = self._active.pop(sandbox_id, None)
        if handle is None:
            return False
        handle.db_path.unlink(missing_ok=True)
        handle.db_path.with_suffix(handle.db_path.suffix + ".wal").unlink(missing_ok=True)
        return True

    def destroy_all(self) -> None:
        for sandbox_id in list(self._active):
            self.delete(sandbox_id)

    @property
    def active(self) -> tuple[SandboxHandle, ...]:
        return tuple(self._active.values())
