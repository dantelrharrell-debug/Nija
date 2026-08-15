from __future__ import annotations

import ast
from pathlib import Path


def _fast_path_installers() -> list[tuple[str, str]]:
    source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_FAST_PATH_INSTALLERS":
                    value = ast.literal_eval(node.value)
                    return list(value)
    raise AssertionError("_FAST_PATH_INSTALLERS not found")


def test_canonical_fast_path_installs_strategy_execution_integrity_before_activation() -> None:
    installers = _fast_path_installers()
    modules = [module for module, _label in installers]

    wrapper = modules.index("bot.trading_engine_strategy_wrapper_patch")
    wiring = modules.index("bot.trading_strategy_apex_wiring_patch")
    integrity = modules.index("bot.strategy_runtime_integrity_patch")
    activation = modules.index("bot.final_production_activation_repair_v61_patch")

    assert wrapper < wiring < integrity < activation


def test_strategy_integrity_guards_are_not_optional_on_canonical_path() -> None:
    source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    optional: set[str] | None = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_FAST_PATH_COMPAT_OPTIONAL_GUARDS":
                    call = node.value
                    assert isinstance(call, ast.Call)
                    optional = set(ast.literal_eval(call.args[0]))
    assert optional is not None
    assert "TRADING_ENGINE_STRATEGY_WRAPPER" not in optional
    assert "TRADING_STRATEGY_APEX_WIRING" not in optional
    assert "STRATEGY_RUNTIME_INTEGRITY" not in optional
