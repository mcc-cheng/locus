"""The Locus sidecar entrypoint (Phase 7.2).

This is what PyInstaller freezes and what the Tauri shell launches. It:
  1. resolves a per-user data directory (the warehouse lives here),
  2. picks a free TCP port (or honours ``LOCUS_PORT``),
  3. writes the chosen port to ``LOCUS_PORT_FILE`` so the shell can find it,
  4. serves the FastAPI app on 127.0.0.1 only (never exposed to the network).

Run frozen as the bundled binary, or in dev as ``python -m api.sidecar``.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from api.rest import create_app


def default_data_dir() -> Path:
    """Per-user data directory for the warehouse."""
    if env := os.environ.get("LOCUS_DATA"):
        return Path(env)
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Locus"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home)) / "Locus"
    return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "Locus"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def resolve_port() -> int:
    env = os.environ.get("LOCUS_PORT")
    return int(env) if env and env.isdigit() and int(env) > 0 else _free_port()


def run(
    data_dir: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    port_file: str | Path | None = None,
) -> None:
    import uvicorn

    data_dir = Path(data_dir) if data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    port = port or resolve_port()
    app = create_app(data_dir)

    pf = port_file or os.environ.get("LOCUS_PORT_FILE")
    if pf:
        Path(pf).write_text(str(port), encoding="utf-8")

    print(
        f"Locus engine running at http://{host}:{port}  (data dir: {data_dir})\n"
        f"  • health:   http://{host}:{port}/health\n"
        f"  • API docs: http://{host}:{port}/docs\n"
        "Leave this running and start the UI in another terminal "
        "(npm --prefix frontend run dev). Press Ctrl+C to stop.",
        flush=True,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def _dispatch_sandbox(argv: list[str]) -> int:
    """Frozen-binary self-dispatch: when PyInstaller freezes this entrypoint,
    ``sys.executable`` is the app binary (not a Python interpreter), so the
    sandbox runtime re-invokes us with these subcommands instead of a .py file."""
    cmd = argv[0]
    if cmd == "exec-script":
        from executor import _bootstrap

        sys.argv = [sys.argv[0], argv[1]]  # _bootstrap reads argv[1]
        return _bootstrap.main()
    if cmd == "exec-notebook":
        import os
        import socket

        _Real = socket.socket

        class _NoNet(_Real):  # type: ignore[misc, valid-type]
            def connect(self, *a, **k):
                raise OSError("network disabled in sandbox")

        socket.socket = _NoNet  # type: ignore[assignment]
        import papermill as pm

        pm.execute_notebook(
            argv[1],
            argv[2],
            parameters={"db_path": os.environ["LOCUS_SANDBOX_DB"]},
            progress_bar=False,
        )
        return 0
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("exec-script", "exec-notebook"):
        sys.exit(_dispatch_sandbox(args))
    run()


if __name__ == "__main__":
    main()
