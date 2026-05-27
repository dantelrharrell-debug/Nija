"""Ensure direct broker.execute_order calls do not bypass ExecutionPipeline."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import List, Tuple


BOT_DIR = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {"tests", "archive"}


def _contains_broker_identifier(node: ast.AST) -> bool:
    current = node
    while isinstance(current, ast.Attribute):
        attr = current.attr.lower()
        if attr == "broker" or attr.endswith("_broker"):
            return True
        current = current.value
    if isinstance(current, ast.Name):
        ident = current.id.lower()
        return ident == "broker" or ident.endswith("_broker")
    return False


def _collect_direct_execute_calls(path: Path) -> List[Tuple[int, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "execute_order":
            continue
        if not _contains_broker_identifier(node.func.value):
            continue
        line_no = int(getattr(node, "lineno", 0) or 0)
        snippet = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else "execute_order(...)"
        violations.append((line_no, snippet))
    return violations


class TestExecutionPipelineRoutingEnforcement(unittest.TestCase):
    """Direct broker execution calls should not exist in runtime bot modules."""

    def test_no_direct_broker_execute_order_calls(self) -> None:
        findings: List[str] = []
        for path in BOT_DIR.rglob("*.py"):
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                continue
            for line_no, snippet in _collect_direct_execute_calls(path):
                findings.append(f"{path.relative_to(BOT_DIR.parent)}:{line_no}: {snippet}")

        self.assertEqual(
            findings,
            [],
            "Direct broker.execute_order usage found; route through submit_market_order_via_pipeline:\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
