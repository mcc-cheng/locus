# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Locus sidecar (Phase 7.2).

Freezes src/api/sidecar.py into a self-contained directory bundle that includes
the Python runtime, all Locus packages, DuckDB, FastAPI/uvicorn, and the optional
biomedical + experiment stacks (rdkit, scikit-learn, pandas, matplotlib,
papermill, ipykernel). The frozen binary self-dispatches sandbox execution
(see api/sidecar.py), so sys.executable can run scripts/notebooks even when it is
the app binary rather than a Python interpreter.

Build (from repo root):
    pyinstaller packaging/locus_sidecar.spec --noconfirm
Output: dist/locus-sidecar/  (a onedir bundle; binary: dist/locus-sidecar/locus-sidecar)
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

SRC = os.path.abspath(os.path.join(os.getcwd(), "src"))
sys.path.insert(0, SRC)

datas = []
binaries = []
hiddenimports = []

# Heavy third-party packages with data files / dynamic submodules.
for pkg in (
    "duckdb",
    "scipy",
    "sklearn",
    "pandas",
    "numpy",
    "matplotlib",
    "papermill",
    "ipykernel",
    "nbformat",
    "nbclient",
    "jupyter_client",
    "rdkit",
    "ollama",
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "multipart",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] skipping {pkg}: {exc}")

# Our own source packages (not pip-installed; discovered from src/).
for pkg in ("warehouse", "ingest", "services", "api", "executor", "agentic"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] skipping submodules of {pkg}: {exc}")

# uvicorn loads these lazily.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [os.path.join(SRC, "api", "sidecar.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="locus-sidecar",
    console=True,
    disable_windowed_traceback=False,
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="locus-sidecar",
)
