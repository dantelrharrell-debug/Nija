#!/usr/bin/env python3
"""Block direct broker.execute_order usage outside the pipeline helper path."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


EXCLUDED_PATH_PARTS = {"archive", "tests", ".pre-commit-hooks"}


def staged_python_files() -> List[Path]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    files = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip().endswith(".py")]
    return files


def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if EXCLUDED_PATH_PARTS.intersection(parts):
        return True
    name = path.name.lower()
    return name.startswith("test_") or name.endswith("_test.py")


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


def find_violations(path: Path) -> List[Tuple[int, str]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception:
        return []

    lines = source.splitlines()
    violations: List[Tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "execute_order":
            continue
        if not _contains_broker_identifier(func.value):
            continue
        lineno = int(getattr(node, "lineno", 0) or 0)
        snippet = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else "execute_order(...)"
        violations.append((lineno, snippet))
    return violations


def iter_violations(paths: Iterable[Path]) -> List[Tuple[Path, int, str]]:
    findings: List[Tuple[Path, int, str]] = []
    for path in paths:
        if is_excluded(path):
            continue
        for line_no, snippet in find_violations(path):
            findings.append((path, line_no, snippet))
    return findings


def main() -> int:
    paths = staged_python_files()
    if not paths:
        return 0

    violations = iter_violations(paths)
    if not violations:
        return 0

    print("❌ Direct broker.execute_order usage is blocked.")
    print("Use bot.pipeline_order_submitter.submit_market_order_via_pipeline instead.\n")
    for path, line_no, snippet in violations:
        print(f" - {path}:{line_no}: {snippet}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
