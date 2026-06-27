from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def test_sidecar_serves_and_writes_port(tmp_path):
    port_file = tmp_path / "port.txt"
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "PYTHONPATH": str(SRC),
        "ANNULUS_DATA": str(tmp_path / "data"),
        "ANNULUS_PORT_FILE": str(port_file),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "api.sidecar"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Wait for the port file.
        for _ in range(100):
            if port_file.exists() and port_file.read_text().strip():
                break
            if proc.poll() is not None:
                raise AssertionError(f"sidecar exited early: {proc.stderr.read().decode()}")
            time.sleep(0.1)
        port = int(port_file.read_text().strip())

        # Poll /health until the server is up.
        ok = False
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    if r.status == 200:
                        ok = True
                        break
            except Exception:
                time.sleep(0.1)
        assert ok, "sidecar /health never responded"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
