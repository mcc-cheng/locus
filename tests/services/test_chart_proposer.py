from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import DeterministicIngestor
from services import ChartSuggestion, VisualizationService
from services import suggestions_store
from services.chart_proposer import ChartProposalSet, ProposedChart
from warehouse import Warehouse

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
    section = DeterministicIngestor(wh).ingest(p, ts).section
    wh.close()
    return root, section


class FakeProposer:
    def __init__(self, charts):
        self._set = ChartProposalSet(charts=charts)

    def ensure_available(self):
        return None

    def propose(self, profile):
        return self._set


def _gen(root, section, charts):
    with VisualizationService.open(root) as viz:
        return viz.generate_suggestions(section, "raw", FakeProposer(charts))


def test_valid_proposals_pass(assay_root):
    root, section = assay_root
    out = _gen(root, section, [
        ProposedChart(type="scatter", title="Dose vs response", rationale="trend", x="dose", y="response"),
        ProposedChart(type="box", title="Response by compound", x="compound", y="response"),
    ])
    assert {s.request.type for s in out} == {"scatter", "box"}
    assert out[0].rationale == "trend"


def test_hallucinated_column_dropped(assay_root):
    root, section = assay_root
    out = _gen(root, section, [
        ProposedChart(type="scatter", x="nope", y="response"),       # bad x
        ProposedChart(type="histogram", x="response"),               # valid
    ])
    assert [s.request.type for s in out] == ["histogram"]


def test_unknown_type_dropped(assay_root):
    root, section = assay_root
    out = _gen(root, section, [
        ProposedChart(type="sankey", x="dose", y="response"),        # no such builder
        ProposedChart(type="scatter", x="dose", y="response"),
    ])
    assert [s.request.type for s in out] == ["scatter"]


def test_non_numeric_on_numeric_role_dropped(assay_root):
    root, section = assay_root
    out = _gen(root, section, [
        ProposedChart(type="histogram", x="compound"),               # compound is categorical
    ])
    assert out == []


def test_high_cardinality_category_dropped(tmp_path):
    # A column with >50 distinct values is not a sane bar/box category.
    ts = datetime(2026, 6, 11, tzinfo=timezone.utc)
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    # code: 60 distinct (id-like category); value: repeats, a normal numeric.
    lines = ["code,value"] + [f"C{i},{(i % 20) * 1.5}" for i in range(60)]
    p = tmp_path / "wide.csv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    section = DeterministicIngestor(wh).ingest(p, ts).section
    wh.close()
    out = _gen(root, section, [
        ProposedChart(type="box", x="code", y="value"),              # code: 60 distinct
        ProposedChart(type="histogram", x="value"),                  # valid
    ])
    assert [s.request.type for s in out] == ["histogram"]


def test_correlation_matrix_needs_two_numerics(assay_root):
    root, section = assay_root
    out = _gen(root, section, [ProposedChart(type="correlation_matrix")])
    assert [s.request.type for s in out] == ["correlation_matrix"]  # dose + response


def test_dedup_and_cap(assay_root):
    root, section = assay_root
    dup = ProposedChart(type="scatter", x="dose", y="response")
    out = _gen(root, section, [dup, dup, dup])
    assert len(out) == 1


def test_cache_round_trip(assay_root, tmp_path):
    root, section = assay_root
    out = _gen(root, section, [ProposedChart(type="histogram", title="t", rationale="r", x="dose")])
    suggestions_store.write(root, section, "raw", out)
    back = suggestions_store.read(root, section, "raw")
    assert back is not None
    assert [s.model_dump() for s in back] == [s.model_dump() for s in out]
    assert isinstance(back[0], ChartSuggestion)


def test_cache_absent_returns_none(assay_root):
    root, section = assay_root
    assert suggestions_store.read(root, section, "raw") is None
