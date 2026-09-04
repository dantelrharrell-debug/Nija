"""Regression tests for source-level execution readiness ownership.

The canonical strategy publisher may publish ``strategy_ready`` but must never
publish ``execution_ready``.  A broker being wired/connected is not fill proof.
"""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "strategy_publication_patch.py"


def _publish_node() -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_publish":
            return node
    raise AssertionError("strategy_publication_patch._publish missing")


def test_strategy_publish_never_marks_execution_ready() -> None:
    node = _publish_node()
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        if not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and first.value == "execution_ready":
            raise AssertionError(
                "strategy publication must not grant execution_ready; "
                "canonical confirmed-fill proof owns that readiness"
            )


def test_strategy_publish_still_marks_strategy_ready() -> None:
    node = _publish_node()
    values = {
        call.args[0].value
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }
    assert "strategy_ready" in values


def test_source_documents_execution_proof_owner() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "execution_ready_unchanged=true" in source
    assert "execution_proof_owner=canonical_v169_v231_v238_v346" in source
