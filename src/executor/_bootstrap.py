"""In-subprocess bootstrap for sandbox script execution (Phase 4.1).

Runs as ``python _bootstrap.py <user_script.py>`` inside the resource-limited
child. Reads two env vars:

  LOCUS_SANDBOX_DB   path to the writable clone DuckDB (the ONLY db it knows)
  LOCUS_SANDBOX_OUT  directory to write artifacts (plots) into

It disables network access, pre-binds a few conveniences (``con``, ``pd``,
``plt``, ``np``), runs the user's script, and saves any open matplotlib figures.
"""

from __future__ import annotations

import os
import sys
import traceback


def _disable_network() -> None:
    """Best-effort: block outbound connections so user code can't reach the
    network. We subclass the real socket (so libraries that subclass ``socket``,
    e.g. ``ssl``, still import) and block the actual network actions."""
    import socket

    msg = "network access is disabled inside the Locus sandbox"
    _RealSocket = socket.socket

    class _NoNetSocket(_RealSocket):
        def connect(self, *_a, **_k):
            raise OSError(msg)

        def connect_ex(self, *_a, **_k):
            raise OSError(msg)

    socket.socket = _NoNetSocket  # type: ignore[assignment]

    def _blocked(*_a, **_k):
        raise OSError(msg)

    for name in ("create_connection", "create_server"):
        if hasattr(socket, name):
            setattr(socket, name, _blocked)


def main() -> int:
    _disable_network()
    db_path = os.environ["LOCUS_SANDBOX_DB"]
    out_dir = os.environ["LOCUS_SANDBOX_OUT"]
    user_script = sys.argv[1]

    ns: dict = {"__name__": "__main__", "db_path": db_path, "output_dir": out_dir}

    import duckdb

    con = duckdb.connect(db_path)  # read-write on the CLONE only
    ns["con"] = con

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ns["plt"] = plt
    except Exception:
        plt = None
    for mod, alias in (("pandas", "pd"), ("numpy", "np")):
        try:
            ns[alias] = __import__(mod)
        except Exception:
            pass

    code = open(user_script, encoding="utf-8").read()
    try:
        exec(compile(code, user_script, "exec"), ns)
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if plt is not None:
            for i, num in enumerate(plt.get_fignums()):
                try:
                    plt.figure(num).savefig(os.path.join(out_dir, f"figure_{i + 1}.png"))
                except Exception:
                    pass
        try:
            con.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
