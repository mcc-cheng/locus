"""Sandbox execution runtime (Phase 4.1).

Runs user Python scripts (and papermill notebooks) in a **resource-limited
subprocess**:

  * CPU-time cap and address-space cap via ``setrlimit`` in a preexec hook
    (inherited by any child processes, e.g. a notebook kernel).
  * Wall-clock timeout enforced by the parent; on expiry the whole process group
    is killed (``killpg``), so kernels/grandchildren die too.
  * Network disabled inside the child (see ``_bootstrap.py``).
  * The child is handed ONLY the sandbox clone path — it has no route to the
    canonical warehouse.

Outputs (stdout, stderr, generated plots, executed notebook) are written under
the sandbox's outputs dir and listed in the result, accessible until the sandbox
is destroyed.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .sandbox import SandboxHandle

_BOOTSTRAP = Path(__file__).parent / "_bootstrap.py"
_MB = 1024 * 1024


@dataclass(frozen=True)
class SandboxLimits:
    timeout_s: float = 30.0
    cpu_seconds: int = 25
    memory_mb: int = 4096


class SandboxRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    run_id: str
    kind: Literal["script", "notebook"]
    ok: bool
    exit_code: int
    timed_out: bool
    execution_ms: float
    stdout: str
    stderr: str
    artifacts: tuple[str, ...] = ()


def _preexec(limits: SandboxLimits):
    def apply() -> None:
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 1))
        except (ValueError, OSError):
            pass
        try:
            cap = limits.memory_mb * _MB
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        except (ValueError, OSError):
            # macOS often ignores RLIMIT_AS; the wall-clock + CPU caps still apply.
            pass

    return apply


def _run_process(
    cmd: list[str], env: dict, cwd: Path, timeout_s: float, limits: SandboxLimits
) -> tuple[str, str, int, bool]:
    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=_preexec(limits),
        start_new_session=True,  # own process group, for clean group-kill
    )
    try:
        out, errs = proc.communicate(timeout=timeout_s)
        return out, errs, proc.returncode, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, errs = proc.communicate()
        errs = (errs or "") + f"\n[sandbox] killed: exceeded {timeout_s:g}s wall-clock limit"
        return out or "", errs, -1, True


def _base_env(handle: SandboxHandle, out_dir: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "LOCUS_SANDBOX_DB": str(handle.db_path),
            "LOCUS_SANDBOX_OUT": str(out_dir),
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _list_artifacts(out_dir: Path) -> tuple[str, ...]:
    if not out_dir.exists():
        return ()
    return tuple(sorted(p.name for p in out_dir.iterdir() if p.is_file()))


def run_script(
    handle: SandboxHandle, code: str, *, limits: SandboxLimits | None = None
) -> SandboxRunResult:
    limits = limits or SandboxLimits()
    run_id = uuid.uuid4().hex
    out_dir = handle.outputs_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / "script.py"
    script_path.write_text(code, encoding="utf-8")

    t0 = perf_counter()
    out, errs, rc, timed_out = _run_process(
        [sys.executable, str(_BOOTSTRAP), str(script_path)],
        _base_env(handle, out_dir),
        handle.dir,
        limits.timeout_s,
        limits,
    )
    ms = (perf_counter() - t0) * 1000.0
    return SandboxRunResult(
        sandbox_id=handle.id,
        run_id=run_id,
        kind="script",
        ok=(rc == 0 and not timed_out),
        exit_code=rc,
        timed_out=timed_out,
        execution_ms=round(ms, 3),
        stdout=out,
        stderr=errs,
        artifacts=tuple(a for a in _list_artifacts(out_dir) if a != "script.py"),
    )


_NB_RUNNER = r"""
import os, sys, socket
_Real = socket.socket
class _NoNet(_Real):
    def connect(self, *a, **k): raise OSError("network disabled in sandbox")
    def connect_ex(self, *a, **k): raise OSError("network disabled in sandbox")
socket.socket = _NoNet
def _blocked(*a, **k): raise OSError("network disabled in sandbox")
for _n in ("create_connection", "create_server"):
    if hasattr(socket, _n): setattr(socket, _n, _blocked)
import papermill as pm
inp, outp = sys.argv[1], sys.argv[2]
pm.execute_notebook(inp, outp, parameters={"db_path": os.environ["LOCUS_SANDBOX_DB"]}, progress_bar=False)
"""


def run_notebook(
    handle: SandboxHandle, notebook: dict | str, *, limits: SandboxLimits | None = None
) -> SandboxRunResult:
    """Execute a notebook with papermill. ``notebook`` is a notebook JSON dict or
    a JSON string. The executed notebook is saved as ``executed.ipynb``."""
    limits = limits or SandboxLimits()
    run_id = uuid.uuid4().hex
    out_dir = handle.outputs_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    nb_json = notebook if isinstance(notebook, str) else json.dumps(notebook)
    input_nb = out_dir / "input.ipynb"
    input_nb.write_text(nb_json, encoding="utf-8")
    output_nb = out_dir / "executed.ipynb"

    t0 = perf_counter()
    out, errs, rc, timed_out = _run_process(
        [sys.executable, "-c", _NB_RUNNER, str(input_nb), str(output_nb)],
        _base_env(handle, out_dir),
        handle.dir,
        limits.timeout_s,
        limits,
    )
    ms = (perf_counter() - t0) * 1000.0
    return SandboxRunResult(
        sandbox_id=handle.id,
        run_id=run_id,
        kind="notebook",
        ok=(rc == 0 and not timed_out),
        exit_code=rc,
        timed_out=timed_out,
        execution_ms=round(ms, 3),
        stdout=out,
        stderr=errs,
        artifacts=tuple(a for a in _list_artifacts(out_dir) if a != "input.ipynb"),
    )
