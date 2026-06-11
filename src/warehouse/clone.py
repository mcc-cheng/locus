"""Copy-on-write clones (Phase 1.3).

A clone is a fresh writable DuckDB database with the canonical attached
``READ_ONLY``. Reads of canonical data require no copy; writes land in the
clone; the engine forbids any write from reaching the canonical. Clones are
session-scoped and discarded on session end.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb

from .warehouse import DB_FILENAME

CLONES_DIRNAME = "clones"
DEFAULT_ALIAS = "canonical"


def _sql_str(value: str) -> str:
    """Escape a value for a single-quoted DuckDB string literal."""
    return value.replace("'", "''")


class Clone:
    """A single copy-on-write clone workspace."""

    def __init__(
        self,
        clone_id: str,
        path: Path,
        con: duckdb.DuckDBPyConnection,
        canonical_alias: str,
    ) -> None:
        self.id = clone_id
        self.path = path
        self.con = con
        self.canonical_alias = canonical_alias
        self._closed = False

    def canonical_ref(self, section: str, table: str = "raw") -> str:
        """Qualified, quoted reference to a canonical table from inside the clone."""
        q = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
        return f"{q(self.canonical_alias)}.{q(section)}.{q(table)}"

    def close(self) -> None:
        """Close the clone connection and delete its file. Idempotent."""
        if self._closed:
            return
        self._closed = True
        try:
            self.con.close()
        finally:
            self.path.unlink(missing_ok=True)
            # DuckDB may leave a WAL sidecar.
            self.path.with_suffix(self.path.suffix + ".wal").unlink(missing_ok=True)

    def __enter__(self) -> "Clone":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class CloneManager:
    """Owns all clones created in a session; discards them on session end."""

    def __init__(self, canonical_path: Path, clones_dir: Path, canonical_alias: str) -> None:
        self.canonical_path = canonical_path
        self.clones_dir = clones_dir
        self.canonical_alias = canonical_alias
        self._active: dict[str, Clone] = {}

    @classmethod
    def for_warehouse(
        cls, root: str | Path, *, canonical_alias: str = DEFAULT_ALIAS
    ) -> "CloneManager":
        """Build a manager for a warehouse root, sweeping any stale clone files
        orphaned by a previous crashed session."""
        root = Path(root)
        canonical_path = root / DB_FILENAME
        clones_dir = root / CLONES_DIRNAME
        clones_dir.mkdir(parents=True, exist_ok=True)
        mgr = cls(canonical_path, clones_dir, canonical_alias)
        mgr._sweep_orphans()
        return mgr

    def _sweep_orphans(self) -> None:
        for f in self.clones_dir.glob("*.duckdb*"):
            f.unlink(missing_ok=True)

    def create(self) -> Clone:
        """Create a fresh copy-on-write clone with canonical attached read-only."""
        if not self.canonical_path.exists():
            raise FileNotFoundError(f"no canonical warehouse at {self.canonical_path}")
        clone_id = uuid.uuid4().hex
        path = self.clones_dir / f"{clone_id}.duckdb"
        con = duckdb.connect(str(path))
        con.execute(
            f"ATTACH '{_sql_str(str(self.canonical_path))}' "
            f"AS \"{self.canonical_alias}\" (READ_ONLY)"
        )
        clone = Clone(clone_id, path, con, self.canonical_alias)
        self._active[clone_id] = clone
        return clone

    def discard(self, clone: Clone | str) -> None:
        clone_id = clone if isinstance(clone, str) else clone.id
        c = self._active.pop(clone_id, None)
        if c is not None:
            c.close()

    def discard_all(self) -> None:
        for c in list(self._active.values()):
            c.close()
        self._active.clear()

    @property
    def active(self) -> tuple[Clone, ...]:
        return tuple(self._active.values())

    def __enter__(self) -> "CloneManager":
        return self

    def __exit__(self, *exc) -> None:
        # Session end: discard every clone.
        self.discard_all()
