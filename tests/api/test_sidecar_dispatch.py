"""The frozen binary self-dispatches `exec-script` to the sandbox bootstrap.

We can't freeze here, but we can verify the dispatch routing works by invoking
the sidecar module with the same subcommand the frozen runtime would use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def test_exec_script_dispatch_runs_bootstrap(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    db = tmp_path / "clone.duckdb"  # bootstrap connects (creates) this DuckDB file
    script = tmp_path / "s.py"
    script.write_text("print('DISPATCH_OK', con.execute('SELECT 41+1').fetchone()[0])\n")

    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SRC),
        "ANNULUS_SANDBOX_DB": str(db),
        "ANNULUS_SANDBOX_OUT": str(out_dir),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "api.sidecar", "exec-script", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "DISPATCH_OK 42" in proc.stdout
