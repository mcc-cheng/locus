"""Templated statistical tests for StatTestAction (Phase 5.2).

The agent picks a test name (a strict enum) and column names. This module builds
the actual Python — the model never supplies executable code. Identifiers are
quoted; values are read via ``TRY_CAST`` and never interpolated. The script runs
inside a sandbox (on the clone), so it can never touch the canonical.
"""

from __future__ import annotations

import json

from .actions import StatTestAction

_GROUPED = {"ttest_ind", "mannwhitneyu", "f_oneway"}
_PAIRED = {"pearsonr", "spearmanr", "ttest_rel"}


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def build_stat_script(action: StatTestAction) -> str:
    src = f"{_q(action.section)}.{_q(action.table)}"
    test = action.test

    if test in _PAIRED:
        if len(action.columns) < 2:
            raise ValueError(f"{test} requires two columns")
        c1, c2 = action.columns[0], action.columns[1]
        sql = (
            f"SELECT TRY_CAST({_q(c1)} AS DOUBLE) AS a, TRY_CAST({_q(c2)} AS DOUBLE) AS b "
            f"FROM {src}"
        )
        prep = ["df = df.dropna(subset=['a', 'b'])"]
        run = [f"stat, p = stats.{test}(df['a'].to_numpy(), df['b'].to_numpy())"]
    else:  # grouped
        if not action.group_by:
            raise ValueError(f"{test} requires a group_by column")
        val = action.columns[0]
        sql = (
            f"SELECT TRY_CAST({_q(val)} AS DOUBLE) AS v, CAST({_q(action.group_by)} AS VARCHAR) "
            f"AS g FROM {src}"
        )
        prep = [
            "df = df.dropna(subset=['v'])",
            "groups = [grp['v'].to_numpy() for _, grp in df.groupby('g')]",
        ]
        if test in ("ttest_ind", "mannwhitneyu"):
            run = [
                f"assert len(groups) == 2, '{test} needs exactly 2 groups, got %d' % len(groups)",
                f"stat, p = stats.{test}(groups[0], groups[1])",
            ]
        else:  # f_oneway
            run = [
                "assert len(groups) >= 2, 'f_oneway needs at least 2 groups'",
                f"stat, p = stats.{test}(*groups)",
            ]

    lines = ["import json", "from scipy import stats", "try:", f"    df = con.execute({sql!r}).df()"]
    lines += [f"    {ln}" for ln in prep]
    lines += [f"    {ln}" for ln in run]
    lines.append(
        '    print(json.dumps({"ok": True, "test": %r, "statistic": float(stat), '
        '"pvalue": float(p), "n": int(len(df))}))' % test
    )
    lines += ["except Exception as e:", '    print(json.dumps({"ok": False, "error": str(e)}))']
    return "\n".join(lines) + "\n"


def parse_stat_output(stdout: str) -> dict:
    """Parse the last JSON line emitted by the stat script."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"ok": False, "error": "no result produced"}
