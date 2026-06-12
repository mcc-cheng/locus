# Phase 4 — Sandbox

**Status:** implemented
**Modules:** `src/executor/{sandbox,runtime,_bootstrap}.py`, sandbox routes in `api/rest/app.py`

Scientists run Python/ML experiments against their data with zero risk to the
source.

## 4.1 Runtime

- **Copy-on-write clone, isolated.** Each sandbox is an independent writable copy
  of the canonical, placed in its **own directory outside the warehouse root**
  (`cow_copy_database`, APFS `clonefile` when available). The subprocess receives
  only the sandbox dir, so there is **no filesystem path to the canonical** — a
  sandbox cannot write back to it under any circumstances. (Verified by test:
  canonical bytes are byte-identical after a sandbox rewrites its clone.)
- **Resource-limited subprocess.** CPU-time and address-space caps via
  `setrlimit` (inherited by child processes, e.g. a notebook kernel); wall-clock
  timeout enforced by the parent, which kills the whole process group on expiry.
- **No network.** The child disables socket creation before user code runs
  (best-effort guard; OS-level confinement is a Phase 7 hardening).
- **Stack.** Scripts run with `con` (DuckDB on the clone), `pd`, `np`, `plt`
  (Agg) pre-bound; open matplotlib figures are auto-saved as artifacts. Notebooks
  run via papermill (`db_path` injected as a parameter); the executed notebook is
  saved as an artifact.
- **Results** (stdout, stderr, exit code, timing, artifact filenames) are kept
  under the sandbox dir until the sandbox is destroyed.

## 4.2 API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/sandboxes` | create a sandbox (independent clone), returns `sandbox_id` |
| POST | `/sandboxes/{id}/run` | execute a script or notebook (`kind`, `code`/`notebook`) |
| GET | `/sandboxes/{id}/results` | the latest run's result |
| DELETE | `/sandboxes/{id}` | destroy the sandbox and its outputs |

The sandbox **cannot write back to the canonical DB** — guaranteed structurally
(no path) and reinforced by isolation. Sandboxes are destroyed on explicit
delete or session end.
