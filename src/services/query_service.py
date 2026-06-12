"""Query service (Phase 3.2).

Runs user SQL against a read-only copy-on-write clone (canonical attached
``READ_ONLY``). Enforces **SELECT-only** via DuckDB's own parser, bounds compute
with a **wall-clock timeout** using ``con.interrupt()`` (row limits don't bound
compute — a heavy aggregate over few output rows still burns CPU), paginates the
output, and reports execution time.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import duckdb

from warehouse import CloneManager

from .errors import QueryError, QueryTimeoutError

DEFAULT_TIMEOUT_S = 30.0
MAX_PAGE_SIZE = 1000


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: list[list[Any]] = field(default_factory=list)
    page: int = 1
    page_size: int = 100
    has_more: bool = False
    execution_ms: float = 0.0


class QueryService:
    """Read-only SQL execution against a session clone.

    One clone connection is held for the service's lifetime and reused; queries
    are serialized with a lock (a connection runs one query at a time).
    """

    def __init__(
        self,
        clone_manager: CloneManager,
        *,
        default_timeout_s: float = DEFAULT_TIMEOUT_S,
        max_page_size: int = MAX_PAGE_SIZE,
    ) -> None:
        self._mgr = clone_manager
        self._clone = clone_manager.create()
        # Resolve unqualified names against the read-only canonical.
        self._clone.con.execute(f'USE {_quote(self._clone.canonical_alias)}')
        self._lock = threading.Lock()
        self._default_timeout_s = default_timeout_s
        self._max_page_size = max_page_size

    @classmethod
    def open(cls, root: str | Path, **kwargs) -> "QueryService":
        return cls(CloneManager.for_warehouse(root), **kwargs)

    def close(self) -> None:
        self._mgr.discard_all()

    def __enter__(self) -> "QueryService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- introspection (read-only) --------------------------------------

    def table_columns(self, section: str, table: str) -> list[str]:
        rows = self._clone.con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [section, table],
        ).fetchall()
        return [r[0] for r in rows]

    # ---- execution -------------------------------------------------------

    def _validate_select_only(self, sql: str) -> None:
        try:
            statements = self._clone.con.extract_statements(sql)
        except Exception as exc:  # parse error
            raise QueryError(f"could not parse SQL: {exc}") from exc
        if len(statements) != 1:
            raise QueryError("exactly one statement is allowed (no ';'-separated statements)")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise QueryError("only SELECT queries are allowed (no DDL or DML)")

    def run(
        self,
        sql: str,
        *,
        page: int = 1,
        page_size: int = 100,
        timeout_s: float | None = None,
    ) -> QueryResult:
        self._validate_select_only(sql)
        page = max(1, page)
        page_size = max(1, min(page_size, self._max_page_size))
        offset = (page - 1) * page_size
        timeout = timeout_s if timeout_s is not None else self._default_timeout_s

        inner = sql.strip().rstrip(";")
        # Fetch one extra row to learn whether another page exists.
        wrapped = f"SELECT * FROM (\n{inner}\n) AS _locus_q LIMIT {page_size + 1} OFFSET {offset}"

        with self._lock:
            con = self._clone.con
            timer = threading.Timer(timeout, con.interrupt)
            timer.start()
            t0 = perf_counter()
            try:
                cur = con.execute(wrapped)
                columns = tuple(d[0] for d in cur.description)
                rows = cur.fetchall()
            except duckdb.InterruptException as exc:
                raise QueryTimeoutError(timeout) from exc
            except duckdb.Error as exc:
                raise QueryError(str(exc)) from exc
            finally:
                timer.cancel()
            elapsed_ms = (perf_counter() - t0) * 1000.0

        has_more = len(rows) > page_size
        return QueryResult(
            columns=columns,
            rows=[list(r) for r in rows[:page_size]],
            page=page,
            page_size=page_size,
            has_more=has_more,
            execution_ms=round(elapsed_ms, 3),
        )


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'
