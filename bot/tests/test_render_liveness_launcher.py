from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def test_render_liveness_launch_skips_python_site_startup() -> None:
    root = Path(__file__).resolve().parents[2]
    bootstrap = (root / "scripts" / "production_bootstrap.sh").read_text(
        encoding="utf-8"
    )

    assert "python3 -S -u render_liveness_server.py &" in bootstrap
    assert "_probe_render_liveness" in bootstrap
    assert "http://127.0.0.1:${_RENDER_LIVENESS_PORT}/healthz" in bootstrap
    assert "payload.get(\"status\") != \"alive\"" in bootstrap
    assert "Early Render liveness confirmed" in bootstrap
    assert "isolated_site_startup=true" in bootstrap


def test_render_liveness_server_uses_only_standard_library_imports() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "render_liveness_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots <= set(sys.stdlib_module_names)


def test_render_liveness_server_binds_and_serves_healthz_under_isolated_python() -> None:
    root = Path(__file__).resolve().parents[2]
    server_path = root / "render_liveness_server.py"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    env = os.environ.copy()
    env["PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, "-S", "-u", str(server_path)],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    url = f"http://127.0.0.1:{port}/healthz"
    try:
        payload = None
        for _attempt in range(40):
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise AssertionError(
                    f"liveness server exited before binding; code={process.returncode} output={output}"
                )
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    assert response.status == 200
                    payload = json.loads(response.read().decode("utf-8"))
                    break
            except Exception:
                time.sleep(0.1)

        assert payload is not None, "liveness endpoint never became reachable"
        assert payload["status"] == "alive"
        assert payload["trading_ready"] is False
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
