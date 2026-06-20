from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import DeterministicIngestor
from services import ChartRequest, VisualizationError, VisualizationService
from warehouse import Warehouse

# A plate/assay-shaped dataset for the richer chart types.
ASSAY = (
    "well_row,well_col,compound,dose,response\n"
    "A,1,X,0.1,5\n"
    "A,2,X,1.0,12\n"
    "A,3,X,10.0,30\n"
    "B,1,Y,0.1,4\n"
    "B,2,Y,1.0,9\n"
    "B,3,Y,10.0,25\n"
)


@pytest.fixture
def assay_root(tmp_path: Path) -> tuple[Path, str]:
    ts = datetime(2026, 6, 11, tzinfo=timezone.utc)
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    p = tmp_path / "assay.csv"
    p.write_text(ASSAY, encoding="utf-8")
    res = DeterministicIngestor(wh).ingest(p, ts)
    section = res.section
    wh.close()
    return root, section


def test_histogram(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(type="histogram", section=section, table="raw", x="response", bins=5)
        )
    assert out.spec["mark"] == "bar"
    assert out.spec["data"]["values"] == out.data
    total = sum(row["count"] for row in out.data)
    assert total == 6  # every numeric response counted into some bin


def test_bar_count(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(ChartRequest(type="bar", section=section, table="raw", x="compound"))
    breakdown = {d["category"]: d["value"] for d in out.data}
    assert breakdown == {"X": 3, "Y": 3}


def test_bar_sum_aggregate(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(
                type="bar", section=section, table="raw", x="compound", y="response",
                aggregate="sum",
            )
        )
    breakdown = {d["category"]: d["value"] for d in out.data}
    assert breakdown == {"X": 47.0, "Y": 38.0}


def test_heatmap(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(
                type="heatmap", section=section, table="raw",
                row="well_row", col="well_col", value="response",
            )
        )
    assert out.spec["mark"] == "rect"
    cell = next(d for d in out.data if d["row"] == "A" and d["col"] == "3")
    assert cell["value"] == 30.0


def test_dose_response_with_series(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(
                type="dose_response", section=section, table="raw",
                x="dose", y="response", color="compound",
            )
        )
    assert out.spec["encoding"]["x"]["scale"]["type"] == "log"
    pt = next(d for d in out.data if d["series"] == "X" and d["dose"] == 10.0)
    assert pt["response"] == 30.0


def test_scatter(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(type="scatter", section=section, table="raw", x="dose", y="response")
        )
    assert out.spec["mark"] == "point"
    assert len(out.data) == 6
    assert all(isinstance(d["x"], float) for d in out.data)


def test_heatmap_columns_order_numerically(assay_root):
    # well_col is stored as text "1".."3"; the heatmap must order it numerically,
    # not lexically (which would give 1, 10, 11, ... in a real plate).
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(
                type="heatmap", section=section, table="raw",
                row="well_row", col="well_col", value="response",
            )
        )
    seen = []
    for d in out.data:
        if d["col"] not in seen:
            seen.append(d["col"])
    assert seen == ["1", "2", "3"]
    assert out.spec["encoding"]["x"]["sort"] is None


def test_blank_column_role_treated_as_unset(assay_root):
    # An empty-string optional role must not be treated as a column name.
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(type="scatter", section=section, table="raw", x="dose", y="response", color="")
        )
    assert out.spec["mark"] == "point"
    assert "color" not in out.spec["encoding"]


def test_suggestions_are_data_driven(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        suggestions = viz.suggest(section, "raw")
    assert suggestions, "expected at least one suggestion"
    types = {s.request.type for s in suggestions}
    # well_row/well_col + a numeric value -> a heatmap is suggested.
    assert "heatmap" in types
    # numeric columns -> histograms; categorical -> bar.
    assert "histogram" in types
    # every suggestion is a runnable request with the right section/table.
    for s in suggestions:
        assert s.request.section == section and s.request.table == "raw"
        assert s.title and s.description


def test_missing_required_column_raises(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        with pytest.raises(VisualizationError):
            viz.visualize(ChartRequest(type="histogram", section=section, table="raw"))  # no x
        with pytest.raises(VisualizationError):
            viz.visualize(
                ChartRequest(type="scatter", section=section, table="raw", x="nope", y="response")
            )


# ---- new chart builders -------------------------------------------------


def test_box(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(type="box", section=section, table="raw", x="compound", y="response")
        )
    assert "layer" in out.spec  # layered manual boxplot
    # one summary row per group; whiskers bracket the IQR
    byc = {d["category"]: d for d in out.data}
    assert set(byc) == {"X", "Y"}
    x = byc["X"]
    assert x["lo"] == 5.0 and x["hi"] == 30.0
    assert x["lo"] <= x["q1"] <= x["mid"] <= x["q3"] <= x["hi"]


def test_line_with_series(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(
                type="line", section=section, table="raw", x="dose", y="response", color="compound"
            )
        )
    assert out.spec["mark"]["type"] == "line"
    # x is linear (not log like dose_response)
    assert "scale" not in out.spec["encoding"]["x"]
    pt = next(d for d in out.data if d["series"] == "X" and d["x"] == 10.0)
    assert pt["y"] == 30.0


def test_grouped_bar_count(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(
                type="grouped_bar", section=section, table="raw", x="compound", color="well_row"
            )
        )
    assert out.spec["encoding"]["xOffset"]["field"] == "series"
    # compound X appears in rows A and B
    xcells = {d["series"]: d["value"] for d in out.data if d["category"] == "X"}
    assert xcells == {"A": 3}  # all three X wells are in row A in the fixture


def test_grouped_bar_requires_y_for_aggregate(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        with pytest.raises(VisualizationError):
            viz.visualize(
                ChartRequest(
                    type="grouped_bar", section=section, table="raw",
                    x="compound", color="well_row", aggregate="avg",  # no y
                )
            )


def test_correlation_matrix(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        out = viz.visualize(
            ChartRequest(type="correlation_matrix", section=section, table="raw")
        )
    assert out.spec["mark"] == "rect"
    # dose & response are the numeric columns; diagonal self-corr == 1
    diag = next(d for d in out.data if d["var1"] == "dose" and d["var2"] == "dose")
    assert abs(diag["corr"] - 1.0) < 1e-9
    # dose vs response is strongly positive in the fixture
    off = next(d for d in out.data if d["var1"] == "dose" and d["var2"] == "response")
    assert off["corr"] > 0.5
