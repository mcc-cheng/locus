from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentic import schema_card
from agentic.analyst import AnalystAgent
from ingest import DeterministicIngestor
from services import QueryService, SchemaService
from warehouse import Warehouse
from tests.agentic.conftest import FakeBrain


def _ingest(tmp_path, csv: str):
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    p = tmp_path / "d.csv"
    p.write_text(csv, encoding="utf-8")
    section = DeterministicIngestor(wh).ingest(p, datetime(2026, 6, 21, tzinfo=timezone.utc)).section
    wh.close()
    return root, section


def _card(root, section):
    with SchemaService.open(root) as s:
        manifest = next(d for d in s.list_datasets() if d.name == section)
    with QueryService.open(root) as qs:
        return schema_card.build_card(qs, manifest, schema_card.load_curation(root, section))


# ---- auto-built card --------------------------------------------------------


def test_card_classifies_columns_and_examples(tmp_path):
    root, section = _ingest(tmp_path, "id,grp,score\n1,A,10\n2,A,20\n3,B,30\n4,B,40\n")
    card = _card(root, section)
    kinds = {c["name"]: c["kind"] for c in card["columns"]}
    assert kinds["score"] == "numeric"
    assert kinds["grp"] == "categorical"
    assert kinds["id"] == "id"
    score = next(c for c in card["columns"] if c["name"] == "score")
    assert score["min"] == 10 and score["max"] == 40
    grp = next(c for c in card["columns"] if c["name"] == "grp")
    assert set(grp["categories"]) == {"A", "B"}


def test_card_flags_gotchas(tmp_path):
    # a missing value and a mixed numeric/text column
    root, section = _ingest(tmp_path, "id,score,dose\n1,10,5mg\n2,,7\n3,30,9\n")
    card = _card(root, section)
    blob = " ".join(card["gotchas"])
    assert "missing" in blob  # score has a null
    assert "mixes numbers and text" in blob  # dose is "5mg"/"7"/"9"


def test_render_card_is_compact_text(tmp_path):
    root, section = _ingest(tmp_path, "id,grp,score\n1,A,10\n2,B,20\n")
    text = schema_card.render_card(_card(root, section))
    assert "Columns of" in text and '"score" [numeric' in text


# ---- curation / the define tool ---------------------------------------------


def test_define_persists_and_appears_in_card(tmp_path):
    root, section = _ingest(tmp_path, "id,responder\n1,yes\n2,no\n3,yes\n")
    schema_card.define(root, section, target="dataset", meaning="Trial responses.")
    schema_card.define(root, section, target="column", name="responder",
                       meaning="whether the patient responded", units="yes/no")
    schema_card.define(root, section, target="metric", name="responder_rate",
                       meaning="share with responder=yes",
                       sql="AVG(CASE WHEN \"responder\"='yes' THEN 1.0 ELSE 0 END)")
    text = schema_card.render_card(_card(root, section))
    assert "Trial responses." in text
    assert "whether the patient responded" in text
    assert "responder_rate" in text and "responder=yes" in text


def test_define_via_agent_step(tmp_path):
    root, section = _ingest(tmp_path, "id,responder\n1,yes\n2,no\n")
    from agentic.steps import Define

    steps = [Define(kind="define", section=section, target="metric", name="resp_rate",
                    meaning="fraction responded", sql="AVG(1.0)")]
    agent = AnalystAgent(root, FakeBrain(steps, answer="Saved."))
    turn = agent.handle("the responder rate is the fraction who responded", section=section)
    step = next(e for e in turn.events if e["type"] == "step" and e["tool"] == "define")
    assert "resp_rate" in step["summary"]
    # persisted: shows up in a freshly built card
    assert "resp_rate" in schema_card.render_card(_card(root, section))


# ---- integration with the agent's grounding ---------------------------------


def test_context_uses_schema_card(tmp_path):
    root, section = _ingest(tmp_path, "id,grp,score\n1,A,10\n2,B,20\n")
    agent = AnalystAgent(root, FakeBrain([]))
    ctx = agent._context(section)
    agent._close()
    assert "schema card" in ctx.lower()
    assert '"score" [numeric' in ctx and section in ctx


def test_context_multi_dataset_is_an_index(tmp_path):
    # two datasets, unscoped -> compact index (schema linking), not full dumps
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    for name, body in (("a.csv", "id,x\n1,5\n"), ("b.csv", "id,y\n1,7\n")):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        DeterministicIngestor(wh).ingest(p, datetime(2026, 6, 21, tzinfo=timezone.utc))
    wh.close()
    agent = AnalystAgent(root, FakeBrain([]))
    ctx = agent._context(None)
    agent._close()
    assert "Datasets available" in ctx
