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


def test_missing_required_column_raises(assay_root):
    root, section = assay_root
    with VisualizationService.open(root) as viz:
        with pytest.raises(VisualizationError):
            viz.visualize(ChartRequest(type="histogram", section=section, table="raw"))  # no x
        with pytest.raises(VisualizationError):
            viz.visualize(
                ChartRequest(type="scatter", section=section, table="raw", x="nope", y="response")
            )
