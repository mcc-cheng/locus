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
from .models import ChartRequest, ChartSuggestion, VisualizationResult
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
            "box": self._box,
            "line": self._line,
            "grouped_bar": self._grouped_bar,
            "correlation_matrix": self._correlation_matrix,
        }[req.type]
        return builder(req)

    # ---- data-driven suggestions ----------------------------------------

    def _profile(self, section: str, table: str) -> dict[str, dict]:
        """Per-column stats: distinct count, non-null count, numeric count —
        computed in a single pass over the table."""
        columns = self._qs.table_columns(section, table)
        if not columns:
            raise VisualizationError(f"no table {table!r} in dataset {section!r}")
        parts = []
        for i, c in enumerate(columns):
            q = _q(c)
            parts.append(f'COUNT(DISTINCT {q}) AS d{i}')
            parts.append(f'COUNT({q}) AS nn{i}')
            parts.append(f'COUNT(TRY_CAST({q} AS DOUBLE)) AS num{i}')
        res = self._qs.run(
            f"SELECT COUNT(*) AS n, {', '.join(parts)} FROM {_qt(section, table)}", page_size=1
        )
        row = dict(zip(res.columns, res.rows[0])) if res.rows else {}
        n = int(row.get("n", 0) or 0)
        prof: dict[str, dict] = {}
        for i, c in enumerate(columns):
            distinct = int(row.get(f"d{i}", 0) or 0)
            nn = int(row.get(f"nn{i}", 0) or 0)
            num = int(row.get(f"num{i}", 0) or 0)
            prof[c] = {
                "distinct": distinct,
                "nn": nn,
                "n": n,
                "numeric": nn > 0 and num / nn >= 0.8,
                # id-like: only meaningful once there are enough rows to judge.
                "unique": n >= 20 and distinct >= 0.9 * n,
            }
        return prof

    def suggest(self, section: str, table: str = "raw") -> list[ChartSuggestion]:
        """Suggest charts from the column types actually present in the data."""
        prof = self._profile(section, table)
        cols = list(prof.keys())

        def is_num(c: str) -> bool:
            return prof[c]["numeric"] and not prof[c]["unique"]

        def is_cat(c: str) -> bool:
            return 2 <= prof[c]["distinct"] <= 25 and not prof[c]["unique"]

        def looks(c: str, *words: str) -> bool:
            cl = c.lower()
            return any(w in cl for w in words)

        num_all = [c for c in cols if is_num(c)]
        numerics = [c for c in num_all if prof[c]["distinct"] >= 5]  # continuous-ish
        cats = sorted((c for c in cols if is_cat(c)), key=lambda c: prof[c]["distinct"])
        out: list[ChartSuggestion] = []

        def add(title, desc, **req):
            out.append(
                ChartSuggestion(
                    title=title, description=desc,
                    request=ChartRequest(section=section, table=table, **req),
                )
            )

        # Domain hints first.
        dose = next((c for c in cols if looks(c, "dose", "conc")), None)
        resp = next((c for c in cols if looks(c, "response", "viab", "readout", "effect", "inhib")), None)
        if dose and resp and prof[dose]["numeric"] and prof[resp]["numeric"]:
            series = next((c for c in cats if looks(c, "compound", "drug", "name", "treatment")), None)
            add("Dose-response", f"{resp} vs {dose} (log scale)",
                type="dose_response", x=dose, y=resp, color=series)
        rowc = next((c for c in cols if looks(c, "well_row", "row")), None)
        colc = next((c for c in cols if looks(c, "well_col", "col", "column")), None)
        valc = next((c for c in num_all if looks(c, "readout", "value", "signal", "intensity")), None) or (num_all[0] if num_all else None)
        if rowc and colc and valc and rowc != colc:
            add("Plate heatmap", f"{valc} across {rowc} × {colc}",
                type="heatmap", row=rowc, col=colc, value=valc)

        # Distributions for numeric columns.
        for c in numerics[:3]:
            add(f"Distribution of {c}", "Histogram", type="histogram", x=c)

        # Category breakdowns.
        for c in cats[:3]:
            add(f"Count by {c}", "Bar chart", type="bar", x=c)

        # Numeric by category (averages).
        if cats and numerics:
            add(f"Average {numerics[0]} by {cats[0]}", "Bar chart",
                type="bar", x=cats[0], y=numerics[0], aggregate="avg")

        # A scatter of the first two numeric columns.
        if len(numerics) >= 2:
            color = cats[0] if cats else None
            add(f"{numerics[0]} vs {numerics[1]}", "Scatter",
                type="scatter", x=numerics[0], y=numerics[1], color=color)

        # De-dup by (type + key columns), cap to 8.
        seen, deduped = set(), []
        for s in out:
            key = (s.request.type, s.request.x, s.request.y, s.request.row, s.request.col, s.request.value)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        return deduped[:8]

    # ---- agentic suggestions --------------------------------------------

    # Per chart type: (required roles, roles that must be numeric).
    _ROLE_RULES = {
        "histogram": (("x",), ("x",)),
        "bar": (("x",), ()),
        "heatmap": (("row", "col", "value"), ("value",)),
        "dose_response": (("x", "y"), ("x", "y")),
        "scatter": (("x", "y"), ("x", "y")),
        "box": (("x", "y"), ("y",)),
        "line": (("x", "y"), ("x", "y")),
        "grouped_bar": (("x", "color"), ()),
        "correlation_matrix": ((), ()),
    }
    # Roles that must be a sane category (low cardinality, not an id column).
    _CAT_ROLES = {
        "bar": ("x",),
        "box": ("x",),
        "grouped_bar": ("x", "color"),
        "heatmap": ("row", "col"),
    }
    _TYPE_LABEL = {
        "histogram": "Histogram", "bar": "Bar", "heatmap": "Heatmap",
        "dose_response": "Dose-response", "scatter": "Scatter", "box": "Box plot",
        "line": "Line", "grouped_bar": "Grouped bar", "correlation_matrix": "Correlations",
    }

    def _model_profile(self, section: str, table: str) -> dict:
        """A compact, model-friendly description of the table for the proposer."""
        prof = self._profile(section, table)
        cols = list(prof.keys())
        n = prof[cols[0]]["n"] if cols else 0
        columns = []
        for c in cols:
            res = self._qs.run(
                f"SELECT DISTINCT {_q(c)} AS v FROM {_qt(section, table)} "
                f"WHERE {_q(c)} IS NOT NULL LIMIT 5",
                page_size=5,
            )
            columns.append(
                {
                    "name": c,
                    "numeric": prof[c]["numeric"],
                    "distinct": prof[c]["distinct"],
                    "id_like": prof[c]["unique"],
                    "samples": [r[0] for r in res.rows],
                }
            )
        return {"table": table, "row_count": n, "columns": columns}

    def generate_suggestions(self, section: str, table: str, proposer) -> list[ChartSuggestion]:
        """Ask the proposer for charts and return only the ones that validate
        against the real data. May raise OllamaUnavailableError / ProposalError —
        the caller decides whether to fall back to :meth:`suggest`."""
        profile = self._model_profile(section, table)
        proposal_set = proposer.propose(profile)
        return self._validate_proposals(section, table, proposal_set.charts)

    def _validate_proposals(self, section: str, table: str, charts) -> list[ChartSuggestion]:
        from .chart_proposer import PALETTE

        prof = self._profile(section, table)
        existing = set(prof.keys())
        numerics = {c for c, p in prof.items() if p["numeric"] and not p["unique"]}

        def cat_ok(col: str) -> bool:
            p = prof.get(col)
            return bool(p) and not p["unique"] and p["distinct"] <= 50

        out: list[ChartSuggestion] = []
        seen: set = set()
        for ch in charts:
            t = ch.type
            if t not in PALETTE:
                continue
            roles = {
                "x": ch.x, "y": ch.y, "color": ch.color,
                "row": ch.row, "col": ch.col, "value": ch.value,
            }
            roles = {
                k: (v.strip() if isinstance(v, str) else v) or None for k, v in roles.items()
            }
            agg = ch.aggregate if ch.aggregate in ("count", "sum", "avg", "min", "max") else "count"

            required, numeric_roles = self._ROLE_RULES[t]
            req_roles, numeric_req = set(required), set(numeric_roles)
            if t in ("bar", "grouped_bar") and agg != "count":
                req_roles.add("y")
                numeric_req.add("y")
            if t == "correlation_matrix" and len(numerics) < 2:
                continue

            ok = True
            for r in req_roles:
                col = roles.get(r)
                if not col or col not in existing:
                    ok = False
                    break
                if r in numeric_req and col not in numerics:
                    ok = False
                    break
            if ok:
                for r in self._CAT_ROLES.get(t, ()):
                    col = roles.get(r)
                    if col and not cat_ok(col):
                        ok = False
                        break
            if not ok:
                continue

            present = {k: v for k, v in roles.items() if v}
            try:
                request = ChartRequest(
                    type=t, section=section, table=table, aggregate=agg, **present
                )
            except Exception:
                continue
            key = (t, request.x, request.y, request.color, request.row, request.col, request.value)
            if key in seen:
                continue
            seen.add(key)
            title = (ch.title or self._TYPE_LABEL[t]).strip()
            out.append(
                ChartSuggestion(
                    title=title,
                    description=self._TYPE_LABEL[t],
                    request=request,
                    rationale=(ch.rationale.strip() or None) if ch.rationale else None,
                )
            )
            if len(out) >= 6:
                break
        return out

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
        # Order numerically when the labels are numbers (so plate columns read
        # 1,2,…,12 not 1,10,11,12,2). The Vega encoding uses data order
        # (`sort: null`) to honour it.
        sql = (
            f"SELECT {r} AS row, {c} AS col, avg(TRY_CAST({v} AS DOUBLE)) AS value "
            f"FROM {_qt(req.section, req.table)} GROUP BY row, col "
            f"ORDER BY TRY_CAST({r} AS DOUBLE) NULLS LAST, {r}, "
            f"TRY_CAST({c} AS DOUBLE) NULLS LAST, {c}"
        )
        columns, rows, truncated, ms = self._run(sql)
        spec = {
            "mark": "rect",
            "encoding": {
                "x": {"field": "col", "type": "ordinal", "title": cols["col"], "sort": None},
                "y": {"field": "row", "type": "ordinal", "title": cols["row"], "sort": None},
                "color": {
                    "field": "value",
                    "type": "quantitative",
                    "title": cols["value"],
                    "scale": {"scheme": "viridis"},
                },
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

    def _box(self, req: ChartRequest) -> VisualizationResult:
        """Box plot of a numeric ``y`` grouped by a categorical ``x``.

        The 5-number summary is computed server-side (one row per group) and
        rendered as a layered rule (whiskers) + bar (IQR) + tick (median) — the
        full per-row values never leave DuckDB.
        """
        cols = self._require_columns(req, {"x": req.x, "y": req.y})
        x, y = _q(cols["x"]), _q(cols["y"])
        src = _qt(req.section, req.table)
        num = f"TRY_CAST({y} AS DOUBLE)"
        sql = (
            f"SELECT {x} AS category, "
            f"min({num}) AS lo, quantile_cont({num}, 0.25) AS q1, "
            f"median({num}) AS mid, quantile_cont({num}, 0.75) AS q3, "
            f"max({num}) AS hi, count({num}) AS n "
            f"FROM {src} WHERE {num} IS NOT NULL GROUP BY category "
            f"ORDER BY category"
        )
        columns, rows, truncated, ms = self._run(sql)
        base = {"x": {"field": "category", "type": "nominal", "title": cols["x"]}}
        spec = {
            "layer": [
                {
                    "mark": {"type": "rule"},
                    "encoding": {
                        **base,
                        "y": {"field": "lo", "type": "quantitative", "title": cols["y"]},
                        "y2": {"field": "hi"},
                    },
                },
                {
                    "mark": {"type": "bar", "size": 24},
                    "encoding": {
                        **base,
                        "y": {"field": "q1", "type": "quantitative"},
                        "y2": {"field": "q3"},
                        "color": {"field": "category", "type": "nominal", "legend": None},
                    },
                },
                {
                    "mark": {"type": "tick", "size": 24, "color": "white"},
                    "encoding": {**base, "y": {"field": "mid", "type": "quantitative"}},
                },
            ]
        }
        return self._result(spec, columns, rows, truncated, ms)

    def _line(self, req: ChartRequest) -> VisualizationResult:
        """Average ``y`` over an ordered numeric ``x``, optional multi-series."""
        cols = self._require_columns(req, {"x": req.x, "y": req.y})
        x, y = _q(cols["x"]), _q(cols["y"])
        src = _qt(req.section, req.table)
        xnum = f"TRY_CAST({x} AS DOUBLE)"
        ynum = f"avg(TRY_CAST({y} AS DOUBLE))"
        if req.color:
            self._require_columns(req, {"color": req.color})
            series = _q(req.color)
            sql = (
                f"SELECT {series} AS series, {xnum} AS x, {ynum} AS y FROM {src} "
                f"WHERE {xnum} IS NOT NULL GROUP BY series, x ORDER BY series, x"
            )
            out_cols = ("series", "x", "y")
        else:
            sql = (
                f"SELECT {xnum} AS x, {ynum} AS y FROM {src} "
                f"WHERE {xnum} IS NOT NULL GROUP BY x ORDER BY x"
            )
            out_cols = ("x", "y")
        columns, rows, truncated, ms = self._run(sql)
        encoding = {
            "x": {"field": "x", "type": "quantitative", "title": cols["x"]},
            "y": {"field": "y", "type": "quantitative", "title": cols["y"]},
        }
        if req.color:
            encoding["color"] = {"field": "series", "type": "nominal", "title": req.color}
        spec = {"mark": {"type": "line", "point": True}, "encoding": encoding}
        return self._result(spec, out_cols, rows, truncated, ms)

    def _grouped_bar(self, req: ChartRequest) -> VisualizationResult:
        """Count or aggregate broken down by two categoricals (x × color)."""
        cols = self._require_columns(req, {"x": req.x, "color": req.color})
        if req.aggregate != "count":
            self._require_columns(req, {"y": req.y})
        x, series = _q(cols["x"]), _q(cols["color"])
        agg = self._agg_expr(req, req.y)
        sql = (
            f"SELECT {x} AS category, {series} AS series, {agg} AS value "
            f"FROM {_qt(req.section, req.table)} GROUP BY category, series "
            f"ORDER BY category, series"
        )
        columns, rows, truncated, ms = self._run(sql)
        spec = {
            "mark": "bar",
            "encoding": {
                "x": {"field": "category", "type": "nominal", "title": cols["x"]},
                "xOffset": {"field": "series", "type": "nominal"},
                "y": {"field": "value", "type": "quantitative"},
                "color": {"field": "series", "type": "nominal", "title": req.color},
            },
        }
        return self._result(spec, ("category", "series", "value"), rows, truncated, ms)

    _CORR_MAX_COLS = 12

    def _correlation_matrix(self, req: ChartRequest) -> VisualizationResult:
        """Pairwise Pearson correlation among the table's numeric columns."""
        prof = self._profile(req.section, req.table)
        numerics = [c for c, p in prof.items() if p["numeric"] and not p["unique"]]
        numerics = numerics[: self._CORR_MAX_COLS]
        if len(numerics) < 2:
            raise VisualizationError(
                "correlation_matrix needs at least two numeric columns"
            )
        src = _qt(req.section, req.table)
        pairs = []
        for a in numerics:
            for b in numerics:
                ca, cb = _q(a), _q(b)
                pairs.append(
                    f"corr(TRY_CAST({ca} AS DOUBLE), TRY_CAST({cb} AS DOUBLE))"
                )
        select = ", ".join(f"{expr} AS c{i}" for i, expr in enumerate(pairs))
        _, rows, _, ms = self._run(f"SELECT {select} FROM {src}")
        flat = rows[0] if rows else [None] * len(pairs)
        data_rows = []
        k = 0
        for a in numerics:
            for b in numerics:
                data_rows.append([a, b, flat[k]])
                k += 1
        spec = {
            "mark": "rect",
            "encoding": {
                "x": {"field": "var1", "type": "nominal", "title": None, "sort": numerics},
                "y": {"field": "var2", "type": "nominal", "title": None, "sort": numerics},
                "color": {
                    "field": "corr",
                    "type": "quantitative",
                    "title": "correlation",
                    "scale": {"scheme": "blueorange", "domain": [-1, 1]},
                },
            },
        }
        return self._result(spec, ("var1", "var2", "corr"), data_rows, False, ms)
