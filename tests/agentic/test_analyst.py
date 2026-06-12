from __future__ import annotations

import pydantic
import pytest

from agentic import (
    AgentDecision,
    AnalystAgent,
    ChartAction,
    NarrativeAction,
    OllamaBrain,
    QueryAction,
    StatTestAction,
)
from executor import SandboxManager
from tests.agentic.conftest import FakeBrain
from warehouse import sha256_file


# ---- 5.2 strict action union ------------------------------------------------


def test_unknown_action_type_rejected():
    with pytest.raises(pydantic.ValidationError):
        AgentDecision.model_validate({"action": {"type": "delete", "sql": "x"}})


def test_extra_fields_rejected():
    with pytest.raises(pydantic.ValidationError):
        AgentDecision.model_validate(
            {"action": {"type": "query", "sql": "SELECT 1", "danger": "rm -rf"}}
        )


def test_each_action_shape_parses():
    AgentDecision.model_validate({"action": {"type": "query", "sql": "SELECT 1"}})
    AgentDecision.model_validate(
        {"action": {"type": "narrative", "text": "hello"}}
    )


# ---- 5.1 agent core ---------------------------------------------------------


def _agent(root, decision, **kw):
    return AnalystAgent(root, FakeBrain(decision), **kw)


def test_narrative_action(agent_root):
    root, _ = agent_root
    resp = _agent(
        root, AgentDecision(action=NarrativeAction(type="narrative", text="Hi there!"))
    ).handle("hello")
    assert resp.action_type == "narrative"
    assert resp.response == "Hi there!"


def test_query_action_returns_rows(agent_root):
    root, section = agent_root
    decision = AgentDecision(
        narration="Counting rows.",
        action=QueryAction(type="query", sql=f'SELECT count(*) AS n FROM "{section}".raw'),
    )
    resp = _agent(root, decision).handle("how many rows?")
    assert resp.action_type == "query"
    assert resp.sql is not None
    assert resp.result["rows"][0][0] == 6


def test_query_action_rejects_non_select(agent_root):
    root, section = agent_root
    decision = AgentDecision(
        action=QueryAction(type="query", sql=f'DROP TABLE "{section}".raw')
    )
    resp = _agent(root, decision).handle("delete everything")
    assert resp.action_type == "query"
    assert resp.error is not None  # blocked by the query service, not executed


def test_agent_never_writes_canonical(agent_root):
    root, section = agent_root
    canonical = root / "warehouse.duckdb"
    before = sha256_file(canonical)
    # Even a malicious "query" that's really DML is rejected; canonical untouched.
    for sql in (f'DELETE FROM "{section}".raw', 'CREATE TABLE "_locus".x (a int)'):
        _agent(root, AgentDecision(action=QueryAction(type="query", sql=sql))).handle("x")
    assert sha256_file(canonical) == before


def test_chart_action_returns_spec(agent_root):
    root, section = agent_root
    decision = AgentDecision(
        action=ChartAction(
            type="chart", chart_type="scatter", section=section, table="raw",
            x="dose", y="response",
        )
    )
    resp = _agent(root, decision).handle("plot dose vs response")
    assert resp.action_type == "chart"
    assert resp.spec["mark"] == "point"
    assert resp.result["row_count"] == 6


def test_stat_test_pearson(agent_root, tmp_path):
    root, section = agent_root
    mgr = SandboxManager(root, base_dir=tmp_path / "sb")
    try:
        h = mgr.create()
        decision = AgentDecision(
            action=StatTestAction(
                type="stat_test", test="pearsonr", section=section, table="raw",
                columns=("dose", "response"), sandbox_id=h.id,
            )
        )
        resp = _agent(root, decision, sandbox_manager=mgr).handle("correlate dose and response")
        assert resp.action_type == "stat_test"
        assert resp.result["ok"] is True
        assert resp.result["n"] == 6
        assert resp.result["pvalue"] < 0.05  # strong positive correlation
    finally:
        mgr.destroy_all()


def test_stat_test_grouped_ttest(agent_root, tmp_path):
    root, section = agent_root
    mgr = SandboxManager(root, base_dir=tmp_path / "sb")
    try:
        h = mgr.create()
        decision = AgentDecision(
            action=StatTestAction(
                type="stat_test", test="ttest_ind", section=section, table="raw",
                columns=("response",), group_by="grp", sandbox_id=h.id,
            )
        )
        resp = _agent(root, decision, sandbox_manager=mgr).handle("compare groups")
        assert resp.result["ok"] is True
        assert resp.result["n"] == 6
    finally:
        mgr.destroy_all()


def test_stat_test_unknown_sandbox(agent_root):
    root, section = agent_root
    decision = AgentDecision(
        action=StatTestAction(
            type="stat_test", test="pearsonr", section=section, table="raw",
            columns=("dose", "response"), sandbox_id="nope",
        )
    )
    resp = _agent(root, decision, sandbox_manager=SandboxManager(root)).handle("x")
    assert resp.error is not None


# ---- real Ollama (skipped if unavailable) -----------------------------------


def _ollama_ready() -> bool:
    try:
        OllamaBrain().ensure_available()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_ready(), reason="qwen2.5:7b-instruct not available")
def test_real_agent_produces_valid_action(agent_root):
    root, _ = agent_root
    resp = AnalystAgent(root, OllamaBrain()).handle("How many rows are in the dataset?")
    assert resp.action_type in {"query", "chart", "stat_test", "narrative"}
