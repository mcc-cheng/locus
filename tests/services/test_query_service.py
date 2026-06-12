from __future__ import annotations

import pytest

from services.query_service import QueryService
from services.errors import QueryError, QueryTimeoutError


def _orders_section(root):
    from services import SchemaService

    with SchemaService.open(root) as svc:
        return next(d.name for d in svc.list_datasets() if d.source_filename == "orders.csv")


def test_select_returns_rows(sealed_root):
    section = _orders_section(sealed_root)
    with QueryService.open(sealed_root) as q:
        res = q.run(f'SELECT order_id, qty FROM "{section}".fact ORDER BY order_id')
    assert res.columns == ("order_id", "qty")
    assert res.rows[0] == ["1", "3"]
    assert res.execution_ms >= 0
    assert not res.has_more


def test_pagination(sealed_root):
    section = _orders_section(sealed_root)
    with QueryService.open(sealed_root) as q:
        p1 = q.run(f'SELECT order_id FROM "{section}".fact ORDER BY order_id', page=1, page_size=2)
        p2 = q.run(f'SELECT order_id FROM "{section}".fact ORDER BY order_id', page=2, page_size=2)
    assert p1.has_more is True
    assert [r[0] for r in p1.rows] == ["1", "2"]
    assert [r[0] for r in p2.rows] == ["3", "4"]
    assert p2.has_more is False


@pytest.mark.parametrize(
    "sql",
    [
        'CREATE TABLE "_locus".x (a INT)',
        'DROP TABLE "_locus".sections',
        'DELETE FROM "_locus".sections',
        'INSERT INTO "_locus".sections VALUES (1)',
        'UPDATE "_locus".sections SET name = NULL',
        "PRAGMA database_list",
        "ATTACH '/tmp/evil.db' AS evil",
        "COPY (SELECT 1) TO '/tmp/leak.csv'",
        "CALL pragma_version()",
    ],
)
def test_rejects_ddl_and_dml(sealed_root, sql):
    with QueryService.open(sealed_root) as q:
        with pytest.raises(QueryError):
            q.run(sql)


def test_rejects_multiple_statements(sealed_root):
    section = _orders_section(sealed_root)
    with QueryService.open(sealed_root) as q:
        with pytest.raises(QueryError):
            q.run(f'SELECT 1; DROP TABLE "{section}".fact;')


def test_cannot_write_canonical_even_if_validation_bypassed(sealed_root):
    """Defense in depth: the underlying connection is read-only on canonical."""
    section = _orders_section(sealed_root)
    with QueryService.open(sealed_root) as q:
        import duckdb

        with pytest.raises(duckdb.Error):
            q._clone.con.execute(f'DELETE FROM {q._clone.canonical_ref(section, "raw")}')


def test_wall_clock_timeout(sealed_root):
    with QueryService.open(sealed_root) as q:
        with pytest.raises(QueryTimeoutError):
            # A few output rows, but a huge cartesian product to compute.
            q.run(
                "SELECT count(*) FROM range(1000000) a, range(1000000) b",
                timeout_s=0.15,
            )


def test_cte_select_is_allowed(sealed_root):
    section = _orders_section(sealed_root)
    with QueryService.open(sealed_root) as q:
        res = q.run(
            f'WITH t AS (SELECT qty FROM "{section}".fact) SELECT count(*) AS n FROM t'
        )
    assert res.rows[0][0] == 4
