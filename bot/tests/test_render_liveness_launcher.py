from __future__ import annotations

import ast
import sys
from pathlib import Path


def test_render_liveness_launch_skips_python_site_startup() -> None:
    root = Path(__file__).resolve().parents[2]
    bootstrap = (root / "scripts" / "production_bootstrap.sh").read_text(
        encoding="utf-8"
    )

    assert "python3 -S -u render_liveness_server.py &" in bootstrap
    assert "kill -0 \"${_RENDER_LIVENESS_PID}\"" in bootstrap
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
