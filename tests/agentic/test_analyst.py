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
    assert turn.response.strip()  # produced a grounded natural-language answer
