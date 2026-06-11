"""Read-only canonical database handle (Phase 1.3).

The serving layers (schema service, read-only queries) use this. DuckDB's
``read_only=True`` makes the engine itself reject any write, so the read-only
guarantee is enforced below our code, not by convention.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .warehouse import DB_FILENAME


class CanonicalDB:
    """A read-only connection to a sealed canonical warehouse."""

    def __init__(self, path: Path, con: duckdb.DuckDBPyConnection) -> None:
        self.path = path
        self.con = con

    @classmethod
    def open(cls, root: str | Path) -> "CanonicalDB":
        root = Path(root)
        path = root / DB_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"no canonical warehouse at {path}")
        con = duckdb.connect(str(path), read_only=True)
        return cls(path, con)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "CanonicalDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
