from __future__ import annotations

import ast
from pathlib import Path


def _installer_modules() -> list[str]:
    source = Path(__file__).resolve().parents[1].joinpath("bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_FAST_PATH_INSTALLERS":
                    assert isinstance(node.value, ast.Tuple)
                    return [
                        item.elts[0].value
                        for item in node.value.elts
                        if isinstance(item, ast.Tuple)
                        and item.elts
                        and isinstance(item.elts[0], ast.Constant)
                    ]
    raise AssertionError("_FAST_PATH_INSTALLERS not found")


def test_runtime_truth_recovery_precedes_apex_wiring():
    modules = _installer_modules()
    assert modules.index("bot.runtime_truth_convergence_v97_patch") < modules.index(
        "bot.trading_strategy_apex_wiring_patch"
    )


def test_position_timeout_installs_between_v95_and_v96():
    modules = _installer_modules()
    assert modules.index("bot.position_sync_core_handoff_v95_patch") < modules.index(
        "bot.position_sync_timeout_v98_patch"
    ) < modules.index("bot.position_sync_dispatch_authority_v96_patch")
