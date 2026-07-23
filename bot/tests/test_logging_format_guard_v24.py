from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bot" / "logging_format_guard_patch.py"


def _load_module(monkeypatch):
    for name in (
        "LIVE_TRADING",
        "LIVE_CAPITAL_VERIFIED",
        "NIJA_EXECUTION_ACTIVE",
        "NIJA_RUNTIME_TRADING_STATE",
        "DRY_RUN_MODE",
        "PAPER_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    name = "logging_format_guard_v24_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_live_intent_accepts_supported_aliases_and_honors_paper_mode(monkeypatch):
    module = _load_module(monkeypatch)

    monkeypatch.setenv("LIVE_TRADING", "true")
    assert module._live_intent() is True
    monkeypatch.delenv("LIVE_TRADING")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "1")
    assert module._live_intent() is True
    monkeypatch.setenv("PAPER_MODE", "true")
    assert module._live_intent() is False


def test_live_trading_installer_failure_is_not_swallowed(monkeypatch):
    module = _load_module(monkeypatch)
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *a, **k: None)
    module.sys.modules.pop("nija_canonical_broker_startup_convergence_v24", None)

    with pytest.raises(RuntimeError, match="could not load spec"):
        module._install_canonical_broker_startup_convergence()


def test_non_live_installer_failure_remains_diagnostic_only(monkeypatch):
    module = _load_module(monkeypatch)
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *a, **k: None)
    module.sys.modules.pop("nija_canonical_broker_startup_convergence_v24", None)

    module._install_canonical_broker_startup_convergence()
