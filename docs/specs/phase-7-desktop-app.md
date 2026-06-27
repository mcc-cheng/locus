# Phase 7 — Desktop App (Tauri)

**Status:** built & verified — the `.app` and `.dmg` were produced on Apple
Silicon and the app launches: the shell spawns the frozen sidecar, which serves
`/health`. The frozen bundle was independently verified to run DuckDB queries,
matplotlib figure generation, and sklearn/scipy stats.
**Modules:** `src-tauri/`, `packaging/`, `src/api/sidecar.py`

## 7.1 Tauri shell (`src-tauri/`)

`src/lib.rs` shows a **splash window**, spawns the frozen sidecar, and polls
`GET /health` for up to **15 seconds**. On success it opens the main window with
the sidecar URL injected as `window.__ANNULUS_API__` (the frontend reads this in
`main.tsx`); on failure the splash shows the sidecar log and a **Retry** button
(`retry` command). The sidecar is killed when the main window closes. Sidecar
stdout/stderr are redirected to `sidecar.log` in the app data dir.

## 7.2 PyInstaller sidecar (`packaging/annulus_sidecar.spec`, `src/api/sidecar.py`)

The sidecar resolves a per-user data dir, picks a free port (or `ANNULUS_PORT`),
writes it to `ANNULUS_PORT_FILE`, and serves `create_app` on `127.0.0.1` only.
**Verified end-to-end** (`tests/api/test_sidecar.py`): spawned as a subprocess it
writes the port and answers `/health`.

Because a frozen `sys.executable` is the app binary (not a Python interpreter),
the binary **self-dispatches** sandbox execution via `exec-script` /
`exec-notebook` subcommands — so the sandbox runtime works inside the bundle.
**Verified** (`tests/api/test_sidecar_dispatch.py`): `exec-script` routes to the
bootstrap and runs the user script with `con` bound.

The spec bundles all `src/` packages plus DuckDB, FastAPI/uvicorn, and the
optional bio (`rdkit`) and experiment (`scikit-learn`, `pandas`, `matplotlib`,
`papermill`, `ipykernel`) stacks (`collect_all` + `collect_submodules`).

## 7.3 Build pipeline (`packaging/macos/`)

`make dist` runs PyInstaller (→ `packaging/build/annulus-sidecar/`) then
`cargo tauri build --target aarch64-apple-darwin`, producing:

```
src-tauri/target/aarch64-apple-darwin/release/bundle/macos/Biomedical Data Aggregator.app
src-tauri/target/aarch64-apple-darwin/release/bundle/dmg/...dmg
```

`packaging/macos/README.md` documents setup, the build, and the unsigned-app
Gatekeeper bypass (`xattr -cr` or right-click → Open).

## Verification status

- ✅ Sidecar serving + port file + `/health` (real subprocess test).
- ✅ Frozen-dispatch routing for sandbox scripts (real subprocess test).
- ✅ Frontend reads `window.__ANNULUS_API__` and still builds.
- ⚠️ The Rust shell, PyInstaller freeze, and `.app/.dmg` bundling are authored
  per Tauri v2 / PyInstaller conventions but require the native toolchain
  (`cargo tauri`, PyInstaller, app icons) to build — not exercised here.
