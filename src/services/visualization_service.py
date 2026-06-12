"""Visualization service (Phase 3.3).

Accepts a chart request, aggregates the data **server-side** with DuckDB, and
returns a Vega-Lite spec plus the aggregated data payload. Full tables are NEVER
sent to the browser — the payload is capped at 10,000 aggregated rows.

Supported v1 chart types: histogram, bar (category breakdown), spatial heatmap
(plate/well), dose-response curve, scatter.

All numeric roles are read with ``TRY_CAST(... AS DOUBLE)`` and rows that don't
parse are excluded from the *chart* — the stored data is never modified.
"""

from __future__ import annotations

from pathlib import Path

from .errors import VisualizationError
from .models import ChartRequest, VisualizationResult
from .query_service import QueryService

MAX_PAYLOAD_ROWS = 10_000


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _qt(section: str, table: str) -> str:
    return f"{_q(section)}.{_q(table)}"


class VisualizationService:
    def __init__(self, query_service: QueryService) -> None:
        self._qs = query_service

    @classmethod
    def open(cls, root: str | Path) -> "VisualizationService":
        return cls(QueryService.open(root, max_page_size=MAX_PAYLOAD_ROWS))

    def close(self) -> None:
        self._qs.close()

    def __enter__(self) -> "VisualizationService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- helpers ---------------------------------------------------------

    def _require_columns(self, req: ChartRequest, roles: dict[str, str | None]) -> dict[str, str]:
        existing = set(self._qs.table_columns(req.section, req.table))
        if not existing:
            raise VisualizationError(f"no table {req.table!r} in dataset {req.section!r}")
        resolved: dict[str, str] = {}
        for role, col in roles.items():
            if col is None:
                raise VisualizationError(f"chart type {req.type!r} requires a {role!r} column")
            if col not in existing:
                raise VisualizationError(f"column {col!r} not found in {req.section}.{req.table}")
            resolved[role] = col
        return resolved

    def _run(self, sql: str) -> tuple[tuple[str, ...], list[list], bool, float]:
        res = self._qs.run(sql, page=1, page_size=MAX_PAYLOAD_ROWS)
        return res.columns, res.rows, res.has_more, res.execution_ms

    def _result(self, spec, columns, rows, truncated, ms) -> VisualizationResult:
        data = [dict(zip(columns, r)) for r in rows]
        spec = {**spec, "data": {"values": data}, "$schema": "https://vega.github.io/schema/vega-lite/v5.json"}
        return VisualizationResult(
            spec=spec, data=data, row_count=len(data), truncated=truncated, execution_ms=ms
        )

    # ---- dispatch --------------------------------------------------------

    def visualize(self, req: ChartRequest) -> VisualizationResult:
        builder = {
            "histogram": self._histogram,
            "bar": self._bar,
            "heatmap": self._heatmap,
            "dose_response": self._dose_response,
            "scatter": self._scatter,
        }[req.type]
        return builder(req)

    # ---- chart builders --------------------------------------------------

    def _histogram(self, req: ChartRequest) -> VisualizationResult:
        cols = self._require_columns(req, {"x": req.x})
        x = _q(cols["x"])
        src = _qt(req.section, req.table)
        numeric = f"(SELECT TRY_CAST({x} AS DOUBLE) AS v FROM {src} WHERE TRY_CAST({x} AS DOUBLE) IS NOT NULL)"
        cols0, rows0, _, ms0 = self._run(f"SELECT min(v) lo, max(v) hi, count(*) n FROM {numeric}")
        lo, hi, n = (rows0[0] if rows0 else (None, None, 0))
        bins = req.bins
        if not n:
            data_rows: list[list] = []
            ms = ms0
        elif hi == lo:
            data_rows = [[lo, lo, n]]
            ms = ms0
        else:
            binw = (hi - lo) / bins
            cols1, raw, _, ms1 = self._run(
                f"SELECT least({bins - 1}, floor((v - {lo!r}) / {binw!r})) AS bucket, count(*) c "
                f"FROM {numeric} GROUP BY bucket ORDER BY bucket"
            )
            data_rows = [[lo + b * binw, lo + (b + 1) * binw, c] for b, c in raw]
            ms = ms0 + ms1
        columns = ("bin_start", "bin_end", "count")
        spec = {
            "mark": "bar",
            "encoding": {
                "x": {"field": "bin_start", "type": "quantitative", "title": cols["x"]},
                "x2": {"field": "bin_end"},
                "y": {"field": "count", "type": "quantitative"},
            },
        }
        return self._result(spec, columns, data_rows, False, ms)

    def _agg_expr(self, req: ChartRequest, value_col: str | None) -> str:
        if req.aggregate == "count" or value_col is None:
            return "count(*)"
        return f"{req.aggregate}(TRY_CAST({_q(value_col)} AS DOUBLE))"

    def _bar(self, req: ChartRequest) -> VisualizationResult:
        cols = self._require_columns(req, {"x": req.x})
        roles = {"x": req.x}
        if req.aggregate != "count":
            roles["y"] = req.y
            self._require_columns(req, {"y": req.y})
        x = _q(cols["x"])
        agg = self._agg_expr(req, req.y)
        sql = (
            f"SELECT {x} AS category, {agg} AS value FROM {_qt(req.section, req.table)} "
            f"GROUP BY category ORDER BY value DESC NULLS LAST"
        )
        columns, rows, truncated, ms = self._run(sql)
        spec = {
            "mark": "bar",
            "encoding": {
                "x": {"field": "category", "type": "nominal", "sort": "-y", "title": cols["x"]},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
        return self._result(spec, ("category", "value"), rows, truncated, ms)

    def _heatmap(self, req: ChartRequest) -> VisualizationResult:
        cols = self._require_columns(req, {"row": req.row, "col": req.col, "value": req.value})
        r, c, v = _q(cols["row"]), _q(cols["col"]), _q(cols["value"])
        sql = (
            f"SELECT {r} AS row, {c} AS col, avg(TRY_CAST({v} AS DOUBLE)) AS value "
            f"FROM {_qt(req.section, req.table)} GROUP BY row, col ORDER BY row, col"
        )
        columns, rows, truncated, ms = self._run(sql)
        spec = {
            "mark": "rect",
            "encoding": {
                "x": {"field": "col", "type": "ordinal", "title": cols["col"]},
                "y": {"field": "row", "type": "ordinal", "title": cols["row"]},
                "color": {"field": "value", "type": "quantitative", "title": cols["value"]},
            },
        }
        return self._result(spec, ("row", "col", "value"), rows, truncated, ms)

    def _dose_response(self, req: ChartRequest) -> VisualizationResult:
        cols = self._require_columns(req, {"x": req.x, "y": req.y})
        x, y = _q(cols["x"]), _q(cols["y"])
        src = _qt(req.section, req.table)
        if req.color:
            self._require_columns(req, {"color": req.color})
            series = _q(req.color)
            sql = (
                f"SELECT {series} AS series, TRY_CAST({x} AS DOUBLE) AS dose, "
                f"avg(TRY_CAST({y} AS DOUBLE)) AS response FROM {src} "
                f"WHERE TRY_CAST({x} AS DOUBLE) IS NOT NULL GROUP BY series, dose ORDER BY series, dose"
            )
            out_cols = ("series", "dose", "response")
        else:
            sql = (
                f"SELECT TRY_CAST({x} AS DOUBLE) AS dose, avg(TRY_CAST({y} AS DOUBLE)) AS response "
                f"FROM {src} WHERE TRY_CAST({x} AS DOUBLE) IS NOT NULL GROUP BY dose ORDER BY dose"
            )
            out_cols = ("dose", "response")
        columns, rows, truncated, ms = self._run(sql)
        encoding = {
            "x": {"field": "dose", "type": "quantitative", "scale": {"type": "log"}, "title": cols["x"]},
            "y": {"field": "response", "type": "quantitative", "title": cols["y"]},
        }
        if req.color:
            encoding["color"] = {"field": "series", "type": "nominal", "title": req.color}
        spec = {"mark": {"type": "line", "point": True}, "encoding": encoding}
        return self._result(spec, out_cols, rows, truncated, ms)

    def _scatter(self, req: ChartRequest) -> VisualizationResult:
        cols = self._require_columns(req, {"x": req.x, "y": req.y})
        x, y = _q(cols["x"]), _q(cols["y"])
        src = _qt(req.section, req.table)
        color_sel = ""
        out_cols = ["x", "y"]
        if req.color:
            self._require_columns(req, {"color": req.color})
            color_sel = f", {_q(req.color)} AS color"
            out_cols.append("color")
        sql = (
            f"SELECT TRY_CAST({x} AS DOUBLE) AS x, TRY_CAST({y} AS DOUBLE) AS y{color_sel} "
            f"FROM {src} WHERE TRY_CAST({x} AS DOUBLE) IS NOT NULL AND TRY_CAST({y} AS DOUBLE) IS NOT NULL"
        )
        columns, rows, truncated, ms = self._run(sql)
        encoding = {
            "x": {"field": "x", "type": "quantitative", "title": cols["x"]},
            "y": {"field": "y", "type": "quantitative", "title": cols["y"]},
        }
        if req.color:
            encoding["color"] = {"field": "color", "type": "nominal", "title": req.color}
        spec = {"mark": "point", "encoding": encoding}
        return self._result(spec, tuple(out_cols), rows, truncated, ms)
