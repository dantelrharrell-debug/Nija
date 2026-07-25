from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4


MODULE_PATH = Path(__file__).resolve().parents[1] / "no_trade_watchdog_runtime_patch.py"


def _load_module():
    name = f"no_trade_watchdog_dispatch_recovery_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_watchdog_uses_path_loaded_dispatch_bridge(monkeypatch):
    module = _load_module()
    bridge = ModuleType("nija_live_active_dispatch_bridge_patch")
    calls: list[str] = []

    def recover(source: str):
        calls.append(source)
        return True, "started"

    bridge.ensure_live_dispatch = recover
    monkeypatch.setitem(
        sys.modules,
        "nija_live_active_dispatch_bridge_patch",
        bridge,
    )

    recovered, detail = module._recover_live_dispatch()

    assert recovered is True
    assert detail == "started"
    assert calls == ["no_trade_watchdog"]


def test_watchdog_does_not_import_missing_dispatch_bridge(monkeypatch):
    module = _load_module()
    for name in (
        "nija_live_active_dispatch_bridge_patch",
        "bot.live_active_dispatch_bridge_patch",
        "live_active_dispatch_bridge_patch",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    recovered, detail = module._recover_live_dispatch()

    assert recovered is False
    assert detail == "dispatch_bridge_unavailable"
