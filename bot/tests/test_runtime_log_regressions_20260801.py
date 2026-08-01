from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from bot import trading_strategy as strategy_module
from bot import universal_broker_exit_supervisor_patch as exit_supervisor


def _strategy_shell() -> strategy_module.TradingStrategy:
    strategy = strategy_module.TradingStrategy.__new__(strategy_module.TradingStrategy)
    strategy.apex = None
    strategy.nija_core_loop = None
    strategy.execution_engine = None
    strategy.broker = SimpleNamespace()
    strategy._wiring_recovery_lock = threading.Lock()
    strategy._wiring_recovery_last_attempt = 0.0
    strategy._get_active_broker = lambda: strategy.broker
    return strategy


def test_missing_apex_recovers_and_attaches_core_loop(monkeypatch):
    strategy = _strategy_shell()

    class Apex:
        def __init__(self, broker_client):
            self.broker_client = broker_client
            self.execution_engine = object()

    loop = SimpleNamespace(apex=None)
    monkeypatch.setattr(strategy_module, "NIJAApexStrategyV71", Apex)
    monkeypatch.setattr(
        strategy_module,
        "get_nija_core_loop",
        lambda *, apex_strategy, max_positions: loop,
    )

    strategy._ensure_nija_wiring()

    assert isinstance(strategy.apex, Apex)
    assert strategy.apex.broker_client is strategy.broker
    assert strategy.execution_engine is strategy.apex.execution_engine
    assert strategy.nija_core_loop is loop
    assert loop.apex is strategy.apex


def test_failed_apex_recovery_is_rate_limited(monkeypatch):
    strategy = _strategy_shell()
    attempts = 0

    class BrokenApex:
        def __init__(self, broker_client):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("startup dependency not ready")

    monkeypatch.setenv("NIJA_STRATEGY_WIRING_RETRY_SECONDS", "60")
    monkeypatch.setattr(strategy_module, "NIJAApexStrategyV71", BrokenApex)
    monkeypatch.setattr(strategy_module, "get_nija_core_loop", None)

    strategy._ensure_nija_wiring()
    strategy._ensure_nija_wiring()

    assert attempts == 1
    assert strategy.apex is None


def test_exit_registration_is_idempotent_and_replaces_stale_instance(monkeypatch):
    class Broker:
        venue = "kraken"
        account_id = "platform"

    first = Broker()
    replacement = Broker()
    monkeypatch.setattr(exit_supervisor, "_start", lambda: None)
    monkeypatch.setattr(
        exit_supervisor.auto_exit,
        "_broker_label",
        lambda broker: broker.venue,
    )
    exit_supervisor._BROKERS.clear()
    exit_supervisor._STRONG_BROKERS.clear()

    exit_supervisor._register_broker(first)
    exit_supervisor._register_broker(first)
    assert exit_supervisor._snapshot() == [first]

    exit_supervisor._register_broker(replacement)
    assert exit_supervisor._snapshot() == [replacement]


def test_broker_manager_does_not_log_raw_balance_payloads():
    source = Path(strategy_module.__file__).with_name("broker_manager.py").read_text(
        encoding="utf-8"
    )
    assert "BALANCE RESPONSE RAW" not in source
    assert "str(trade_balance)[:1200]" not in source
