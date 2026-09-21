"""Regression guard for canonical fast-path live-capital convergence v425."""

from __future__ import annotations

import ast
from pathlib import Path


def test_canonical_fast_path_installs_live_capital_coordinator_guard():
    source_path = Path(__file__).resolve().parents[1] / "bot.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    specs = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "_FAST_PATH_INSTALLERS" for target in node.targets):
                specs = ast.literal_eval(node.value)
                break

    assert specs is not None
    assert (
        "bot.startup_coordinator_live_capital_state_repair_patch",
        "STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR",
    ) in specs
