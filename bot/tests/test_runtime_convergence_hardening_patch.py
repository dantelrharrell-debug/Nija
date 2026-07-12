from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_convergence_hardening_patch_test_module",
    ROOT / "runtime_convergence_hardening_patch.py",
)
assert SPEC and SPEC.loader
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


def test_broker_identity_is_account_scoped():
    broker = SimpleNamespace(account_id="USER:tania_gilbert", broker_name="kraken")
    assert patch._broker_identity(broker) == "user:tania_gilbert:kraken"


def test_auth_surface_patches_adapter_methods(monkeypatch):
    calls: list[str] = []
    fake_auth = ModuleType("broker_auth_recovery_patch")
    fake_auth.normalize_coinbase_environment = lambda: calls.append("coinbase") or True
    fake_auth.normalize_okx_environment = lambda: calls.append("okx") or True
    real_import = patch.importlib.import_module
    monkeypatch.setattr(
        patch.importlib,
        "import_module",
        lambda name: fake_auth if name == "broker_auth_recovery_patch" else real_import(name),
    )

    module = ModuleType("bot.broker_integration")

    class CoinbaseBrokerAdapter:
        def connect(self):
            calls.append("connect")
            return True

    module.CoinbaseBrokerAdapter = CoinbaseBrokerAdapter
    assert patch._patch_module(module) is True
    assert CoinbaseBrokerAdapter().connect() is True
    assert calls == ["coinbase", "connect"]


def test_zero_signal_streak_is_bounded(monkeypatch):
    module = ModuleType("bot.nija_core_loop")
    seen: list[int] = []

    class NijaCoreLoop:
        def _phase3_scan_and_enter(self, broker, snapshot, symbols, available_slots, zero_signal_streak=0):
            seen.append(zero_signal_streak)
            return (0, 0, 0, {})

    module.NijaCoreLoop = NijaCoreLoop
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")
    assert patch._patch_module(module) is True
    NijaCoreLoop()._phase3_scan_and_enter(None, None, [], 1, 999)
    assert seen == [12]


def test_duplicate_worker_start_is_suppressed(monkeypatch):
    patch._WORKER_REGISTRY.clear()
    module = ModuleType("bot.independent_broker_trader")
    started = threading.Event()
    stop = threading.Event()

    class IndependentBrokerTrader:
        def _start_broker_thread(self, broker):
            thread = threading.Thread(target=lambda: (started.set(), stop.wait(2)), daemon=True)
            thread.start()
            return thread

    module.IndependentBrokerTrader = IndependentBrokerTrader
    assert patch._patch_module(module) is True
    trader = IndependentBrokerTrader()
    broker = SimpleNamespace(account_id="platform", broker_name="kraken")
    first = trader._start_broker_thread(broker)
    assert started.wait(1)
    second = trader._start_broker_thread(broker)
    assert second is first
    stop.set()
    first.join(1)
