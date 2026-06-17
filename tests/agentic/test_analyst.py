from __future__ import annotations

import pydantic
import pytest

from agentic import AnalystAgent, OllamaBrain, StepDecision
from agentic.steps import MakeChart, MakeFigure, RunSql, RunStat
from executor import SandboxManager
from tests.agentic.conftest import FakeBrain
from warehouse import sha256_file


def _agent(root, steps=None, *, answer="Done.", sandbox=None, available=True):
    brain = FakeBrain(steps, answer=answer, available=available)
    return AnalystAgent(root, brain, sandbox_manager=sandbox)


# ---- step union validity ----------------------------------------------------


def test_unknown_step_kind_rejected():
    with pytest.raises(pydantic.ValidationError):
        StepDecision.model_validate({"step": {"kind": "delete_everything"}})


# ---- multi-step loop --------------------------------------------------------


def test_runs_sql_then_answers(agent_root):
    root, section = agent_root
    steps = [RunSql(kind="run_sql", sql=f'SELECT count(*) AS n FROM "{section}".raw')]
    turn = _agent(root, steps, answer="There are 6 rows.").handle("how many rows?")
    assert turn.used_sql and section in turn.used_sql[0]
    assert turn.response == "There are 6 rows."
    kinds = [e["type"] for e in turn.events]
    assert "step" in kinds and "final" in kinds


def test_makes_chart(agent_root):
    root, section = agent_root
    steps = [
        MakeChart(kind="make_chart", chart_type="scatter", section=section, table="raw",
                  x="dose", y="response"),
    ]
    turn = _agent(root, steps).handle("plot dose vs response")
    assert turn.charts, "expected a chart event"
    assert turn.charts[0]["spec"]["mark"] == "point"


def test_runs_stat_in_sandbox(agent_root, tmp_path):
    root, section = agent_root
    mgr = SandboxManager(root, base_dir=tmp_path / "sb")
    try:
        steps = [
            RunStat(kind="run_stat", test="pearsonr", section=section, table="raw",
                    columns=["dose", "response"]),
        ]
        turn = _agent(root, steps, sandbox=mgr).handle("correlate dose and response")
        stat_step = next(e for e in turn.events if e["type"] == "step" and e["tool"] == "run_stat")
        assert "pearsonr" in stat_step["summary"]
        assert "statistic" in stat_step["summary"]
    finally:
        mgr.destroy_all()


def test_make_figure_produces_inline_image(agent_root, tmp_path):
    root, section = agent_root
    mgr = SandboxManager(root, base_dir=tmp_path / "sb")
    try:
        code = (
            f"df = con.execute('SELECT grp, COUNT(*) AS n FROM \"{section}\".raw GROUP BY grp').df()\n"
            "plt.bar(df['grp'], df['n']); plt.title('rows per grp')\n"
        )
        steps = [MakeFigure(kind="make_figure", code=code, caption="rows per grp")]
        turn = _agent(root, steps, sandbox=mgr, answer="Here is the figure.").handle("plot it")
        assert turn.figures, "expected a figure event"
        assert turn.figures[0]["image"].startswith("data:image/png;base64,")
    finally:
        mgr.destroy_all()


def test_make_figure_strips_wrappers_and_backticks(agent_root, tmp_path):
    # Models sometimes wrap code in <python> tags / ```fences and use backticks.
    root, section = agent_root
    mgr = SandboxManager(root, base_dir=tmp_path / "sb")
    try:
        code = (
            "<python>\n"
            f"df = con.execute('SELECT COUNT(*) AS n FROM `{section}`.`raw`').df()\n"
            "plt.bar(['all'], [df['n'][0]])\n"
            "</python>"
        )
        steps = [MakeFigure(kind="make_figure", code=code)]
        turn = _agent(root, steps, sandbox=mgr).handle("plot")
        assert turn.figures, "wrappers/backticks should be normalized and the figure produced"
    finally:
        mgr.destroy_all()


def test_backticks_in_sql_are_normalized(agent_root):
    root, section = agent_root
    # MySQL-style backtick quoting must be accepted (normalized to double quotes).
    steps = [RunSql(kind="run_sql", sql=f"SELECT COUNT(*) AS n FROM `{section}`.`raw`")]
    turn = _agent(root, steps, answer="6 rows.").handle("count")
    sql_step = next(e for e in turn.events if e["type"] == "step" and e["tool"] == "run_sql")
    assert "ERROR" not in (sql_step["summary"] or "")  # ran fine after normalization


def test_bad_sql_is_handled_not_crashed(agent_root):
    root, section = agent_root
    steps = [RunSql(kind="run_sql", sql=f'DROP TABLE "{section}".raw')]
    turn = _agent(root, steps, answer="Couldn't do that.").handle("delete it")
    # The loop observes the rejection and still answers; nothing crashes.
    assert turn.response == "Couldn't do that."
    sql_step = next(e for e in turn.events if e["type"] == "step" and e["tool"] == "run_sql")
    assert "ERROR" in (sql_step["summary"] or "")


def test_agent_never_writes_canonical(agent_root):
    root, section = agent_root
    canonical = root / "warehouse.duckdb"
    before = sha256_file(canonical)
    for sql in (f'DELETE FROM "{section}".raw', 'CREATE TABLE "_locus".x (a int)'):
        _agent(root, [RunSql(kind="run_sql", sql=sql)]).handle("x")
    assert sha256_file(canonical) == before


def test_blocks_when_ollama_unavailable(agent_root):
    root, _ = agent_root
    turn = _agent(root, available=False).handle("hi")
    assert turn.error is not None
    assert any(e["type"] == "error" for e in turn.events)


# ---- real Ollama (skipped if unavailable) -----------------------------------


def _ollama_ready() -> bool:
    try:
        OllamaBrain().ensure_available()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_ready(), reason="qwen2.5:7b-instruct not available")
def test_real_agent_answers_with_data(agent_root):
    root, _ = agent_root
    agent = AnalystAgent(root, OllamaBrain())
    turn = agent.handle("How many rows are in the dataset?")
    # The model either answers directly or asks a clarifying question — both are
    # valid end-to-end outcomes (model behavior is nondeterministic).
    assert turn.response.strip() or turn.asks


# ---- human-in-the-loop (data quality) ---------------------------------------


def _hitl_root(tmp_path):
    """A dataset where the 'score' column has a missing value."""
    from datetime import datetime, timezone
    from ingest import DeterministicIngestor
    from warehouse import Warehouse

    csv = "id,grp,score\n1,A,10\n2,A,\n3,B,30\n4,B,40\n"  # row 2 score is missing
    root = tmp_path / "wh"
    wh = Warehouse.open(root)
    p = tmp_path / "m.csv"
    p.write_text(csv, encoding="utf-8")
    section = DeterministicIngestor(wh).ingest(p, datetime(2026, 6, 16, tzinfo=timezone.utc)).section
    wh.close()
    return root, section


def test_chart_gate_asks_when_data_has_missing_values(tmp_path):
    root, section = _hitl_root(tmp_path)
    steps = [MakeChart(kind="make_chart", chart_type="histogram", section=section, table="raw", x="score")]
    turn = _agent(root, steps).handle("make a histogram of score")
    assert turn.asks, "expected the agent to pause and ask the human"
    assert "missing" in turn.asks[0]["question"].lower()
    assert any("exclude" in o.lower() for o in turn.asks[0]["options"])
    assert not turn.charts  # did NOT silently build


def test_chart_proceeds_after_user_confirms(tmp_path):
    root, section = _hitl_root(tmp_path)
    steps = [MakeChart(kind="make_chart", chart_type="histogram", section=section, table="raw", x="score")]
    # The user's message (a clicked option) signals proceeding -> gate passes.
    turn = _agent(root, steps).handle("Exclude those rows and continue")
    assert turn.charts, "should build the chart once the user agreed to proceed"
    assert not turn.asks


def test_clean_columns_do_not_trigger_a_question(tmp_path):
    root, section = _hitl_root(tmp_path)
    # 'grp' has no missing values -> no gate.
    steps = [MakeChart(kind="make_chart", chart_type="bar", section=section, table="raw", x="grp")]
    turn = _agent(root, steps).handle("bar chart of grp")
    assert turn.charts and not turn.asks


def test_ask_user_step_pauses_with_options(tmp_path):
    root, section = _hitl_root(tmp_path)
    from agentic.steps import AskUser

    steps = [AskUser(kind="ask_user", question="Which cohort?", options=["A", "B"])]
    turn = _agent(root, steps).handle("compare cohorts")
    assert turn.asks and turn.asks[0]["question"] == "Which cohort?"
    assert turn.asks[0]["options"] == ["A", "B"]


def test_check_data_reports_issues(tmp_path):
    root, section = _hitl_root(tmp_path)
    from agentic.steps import CheckData

    steps = [CheckData(kind="check_data", section=section, table="raw", columns=["score"])]
    turn = _agent(root, steps, answer="ok").handle("any problems?")
    check = next(e for e in turn.events if e["type"] == "step" and e["tool"] == "check_data")
    assert "1 missing" in check["summary"]


def test_chart_column_cast_wrapper_is_normalized(agent_root):
    # Model sometimes passes TRY_CAST("col" AS DOUBLE) as the column field.
    root, section = agent_root
    steps = [
        MakeChart(kind="make_chart", chart_type="histogram", section=section, table="raw",
                  x='TRY_CAST("dose" AS DOUBLE)'),
    ]
    turn = _agent(root, steps).handle("histogram of dose")
    assert turn.charts, "cast-wrapped column should be normalized and the chart built"
    chart_step = next(e for e in turn.events if e["type"] == "step" and e["tool"] == "make_chart")
    assert "ERROR" not in (chart_step["summary"] or "")
