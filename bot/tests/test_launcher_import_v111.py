from __future__ import annotations

import ast
from pathlib import Path


def _launcher_source() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "scripts" / "canonical_runtime_launcher_v26.py").read_text(encoding="utf-8")


def test_bootstrap_writer_first_avoids_importlib_import_module() -> None:
    tree = ast.parse(_launcher_source())
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bootstrap_writer_first"
    )
    calls = [node for node in ast.walk(target) if isinstance(node, ast.Call)]
    rendered = [ast.unparse(call.func) for call in calls]

    assert "importlib.import_module" not in rendered
    assert rendered.count("_canonical_import") >= 3


def test_v111_canonical_import_uses_frozen_bootstrap() -> None:
    tree = ast.parse(_launcher_source())
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_canonical_import"
    )
    text = ast.unparse(target)

    assert "_gcd_import" in text
    assert "canonical_import_primitive_unavailable" in text


def test_writer_safety_checks_remain_fail_closed() -> None:
    source = _launcher_source()

    assert "_acquire_writer_authority_before_nonce" in source
    assert "canonical writer bootstrap failed" in source
    assert "canonical writer bootstrap did not establish exact distributed lineage" in source
    assert "assert_distributed_writer_authority" in source
    assert "_release_early_writer" in source
