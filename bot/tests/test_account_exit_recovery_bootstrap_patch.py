from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "account_exit_recovery_bootstrap_patch.py"
    spec = importlib.util.spec_from_file_location(
        "nija_test_account_exit_recovery_bootstrap_patch",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retry_refreshes_capital_authority(monkeypatch):
    module = _load_module()
    calls = []
    manager = SimpleNamespace(
        refresh_capital_authority=lambda **kwargs: calls.append(kwargs) or {
            "ready": True,
            "total_capital": 100.0,
            "valid_brokers": 1,
        }
    )
    trader = SimpleNamespace(multi_account_manager=manager)
    recovery = ModuleType("fake_recovery")
    recovery._retry_all_accounts = lambda value: calls.append(("retry", value))

    assert module._patch_recovery_retry(recovery) is True
    recovery._retry_all_accounts(trader)

    assert calls[0] == ("retry", trader)
    assert calls[1]["trigger"] == "account_exit_recovery:retry_all_accounts"


def test_init_starts_supervisor_before_normal_start(monkeypatch):
    module = _load_module()
    started = threading.Event()
    seen = []
    recovery = ModuleType("fake_recovery")
    recovery._retry_all_accounts = lambda trader: None

    def _start(trader):
        seen.append(trader)
        started.set()

    recovery._start_supervisor = _start
    monkeypatch.setattr(module, "_load_recovery_module", lambda: recovery)

    class Trader:
        def __init__(self):
            self.multi_account_manager = SimpleNamespace()
            self.trading_strategy = object()

    assert module._patch_class(Trader) is True
    trader = Trader()

    assert started.wait(1.0)
    assert seen == [trader]


def test_patch_class_is_idempotent(monkeypatch):
    module = _load_module()
    recovery = ModuleType("fake_recovery")
    recovery._retry_all_accounts = lambda trader: None
    recovery._start_supervisor = lambda trader: None
    monkeypatch.setattr(module, "_load_recovery_module", lambda: recovery)

    class Trader:
        def __init__(self):
            self.count = getattr(self, "count", 0) + 1

    assert module._patch_class(Trader) is True
    wrapped = Trader.__init__
    assert module._patch_class(Trader) is True
    assert Trader.__init__ is wrapped

    trader = Trader()
    assert trader.count == 1


def test_refresh_failure_is_nonfatal():
    module = _load_module()

    class Manager:
        def refresh_capital_authority(self, **kwargs):
            raise RuntimeError("temporary broker outage")

    trader = SimpleNamespace(multi_account_manager=Manager())
    assert module._refresh_capital_authority(trader, "test") == {}
