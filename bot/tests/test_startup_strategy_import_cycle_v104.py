from __future__ import annotations

import builtins
import importlib.util
import sys
from types import ModuleType


def test_v104_defers_only_optional_strategy_dependencies_while_initializing(monkeypatch):
    from bot import startup_strategy_import_cycle_v104_patch as v104

    # Reset the hook to a known baseline for this isolated test process.
    current = builtins.__import__
    original = getattr(builtins, v104._ORIGINAL_ATTR, current)
    monkeypatch.setattr(builtins, "__import__", original)
    monkeypatch.setattr(builtins, v104._HOOK_FLAG, False, raising=False)

    module = ModuleType("bot.trading_strategy")
    spec = importlib.util.spec_from_loader("bot.trading_strategy", loader=None)
    assert spec is not None
    spec._initializing = True  # type: ignore[attr-defined]
    module.__spec__ = spec
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", module)

    assert v104.install() is True

    caller_globals = {"__name__": "bot.trading_strategy"}
    try:
        builtins.__import__("bot.nija_apex_strategy_v71", caller_globals, {}, (), 0)
    except ImportError as exc:
        assert "deferred while canonical TradingStrategy is initializing" in str(exc)
    else:
        raise AssertionError("APEX import should be deferred during canonical strategy initialization")

    # Unrelated imports remain transparent.
    assert builtins.__import__("math", caller_globals, {}, (), 0).__name__ == "math"

    # Once TradingStrategy initialization completes, v104 must become transparent.
    spec._initializing = False  # type: ignore[attr-defined]
    imported = builtins.__import__("bot.nija_core_loop", caller_globals, {}, (), 0)
    assert imported is not None


def test_v104_installs_before_strategy_recovery_chain():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "position_sync_timeout_v98_patch.py").read_text()
    assert "_install_v104" in source
    assert source.index("if not _install_v104()") < source.index("if not _install_v100()")
    assert source.index("if not _install_v104()") < source.index("if not _install_v102()")
