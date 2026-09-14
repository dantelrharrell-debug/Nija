from __future__ import annotations

import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor

from bot.broker_configs.strategy_selector import BrokerStrategySelector
from bot.broker_failure_manager import BrokerFailureManager
from bot.broker_isolation_registry import (
    BrokerCellRuntimeManager,
    BrokerIsolationRegistry,
    CellHealth,
    IsolationEntry,
    IsolationPolicy,
)


def test_broker_halt_does_not_cascade_to_other_cells():
    registry = BrokerIsolationRegistry()
    registry.register(IsolationEntry("kraken", IsolationPolicy.ACTIVE))
    registry.register(IsolationEntry("coinbase", IsolationPolicy.ACTIVE))
    registry.register(IsolationEntry("okx", IsolationPolicy.ACTIVE))
    registry.register(IsolationEntry("alpaca", IsolationPolicy.ACTIVE))

    assert registry.halt_cell("okx", "provider_timeout") is True

    assert registry.get("okx").state.health is CellHealth.HALTED
    for name in ("kraken", "coinbase", "alpaca"):
        assert registry.get(name).state.health is CellHealth.READY
        assert registry.get(name).state.halted_reason == ""


def test_halted_cell_blocks_entries_but_preserves_protective_exits():
    registry = BrokerIsolationRegistry()
    registry.register(IsolationEntry("okx", IsolationPolicy.ACTIVE))
    registry.halt_cell("okx", "circuit_breaker")

    buy_result = registry.check_execution("okx", "buy")
    assert buy_result is not None
    assert buy_result["status"] == "broker_isolated_skip"
    assert registry.check_execution("okx", "sell") is None
    assert registry.check_execution("okx", "close") is None


def test_unknown_broker_fails_closed():
    registry = BrokerIsolationRegistry()
    unknown = registry.get_or_default("mystery_exchange")

    assert unknown.policy is IsolationPolicy.DISABLED
    assert unknown.state.health is CellHealth.DISABLED
    assert registry.check_execution("mystery_exchange", "buy") is not None


def test_disabled_cell_cannot_be_halted_or_degraded():
    registry = BrokerIsolationRegistry()
    registry.register(
        IsolationEntry(
            "disabled_test",
            IsolationPolicy.DISABLED,
            state=types.SimpleNamespace(
                health=CellHealth.DISABLED,
                halted_reason="",
                consecutive_failures=0,
                last_failure="",
                last_failure_ts=0.0,
                last_success_ts=0.0,
                users=set(),
            ),
        )
    )
    # Replace the SimpleNamespace with canonical state through a detached round trip.
    entry = registry.get("disabled_test")
    entry.state.health = CellHealth.DISABLED
    registry.register(entry)

    assert registry.halt_cell("disabled_test", "should_not_change") is False
    assert registry.record_failure("disabled_test", "should_not_change") is False
    assert registry.get("disabled_test").state.health is CellHealth.DISABLED


def test_registry_get_returns_detached_snapshot():
    registry = BrokerIsolationRegistry()
    registry.register(IsolationEntry("kraken", IsolationPolicy.ACTIVE))

    outside = registry.get("kraken")
    outside.state.health = CellHealth.HALTED
    outside.state.users.add("intruder")

    inside = registry.get("kraken")
    assert inside.state.health is CellHealth.READY
    assert inside.state.users == set()


def test_halt_and_resume_reapply_only_cell_owned_passive_mode():
    registry = BrokerIsolationRegistry()
    registry.register(IsolationEntry("okx", IsolationPolicy.ACTIVE))

    class BrokerType:
        value = "okx"

    class Broker:
        broker_type = BrokerType()

        def __init__(self):
            self.mode = "ACTIVE"
            self.exit_only_mode = False

    broker = Broker()
    registry.apply_to_broker(broker)
    assert broker.mode == "ACTIVE"
    assert broker.exit_only_mode is False

    assert registry.halt_cell("okx", "test") is True
    assert broker.mode == "PASSIVE"
    assert broker.exit_only_mode is True

    assert registry.resume_cell("okx") is True
    assert broker.mode == "ACTIVE"
    assert broker.exit_only_mode is False


def test_users_are_members_of_only_their_broker_cells():
    registry = BrokerIsolationRegistry()
    registry.register(IsolationEntry("kraken", IsolationPolicy.ACTIVE))
    registry.register(IsolationEntry("coinbase", IsolationPolicy.ACTIVE))

    registry.register_user("kraken", "user-a")
    registry.register_user("coinbase", "user-b")

    assert registry.get("kraken").state.users == {"user-a"}
    assert registry.get("coinbase").state.users == {"user-b"}

    registry.unregister_user("kraken", "user-a")
    assert registry.get("kraken").state.users == set()
    assert registry.get("coinbase").state.users == {"user-b"}


def test_failure_counter_is_cell_local():
    registry = BrokerIsolationRegistry()
    registry.register(IsolationEntry("kraken", IsolationPolicy.ACTIVE))
    registry.register(IsolationEntry("coinbase", IsolationPolicy.ACTIVE))

    assert registry.record_failure("kraken", "nonce_error", halt_after=2) is False
    assert registry.record_failure("kraken", "nonce_error", halt_after=2) is True

    assert registry.get("kraken").state.health is CellHealth.HALTED
    assert registry.get("kraken").state.consecutive_failures == 2
    assert registry.get("coinbase").state.health is CellHealth.READY
    assert registry.get("coinbase").state.consecutive_failures == 0


def test_failure_manager_leaves_failed_broker_capital_idle(monkeypatch):
    import bot.broker_failure_manager as bfm_module

    monkeypatch.setattr(bfm_module, "_halt_broker_cell", lambda *_args, **_kwargs: None)
    manager = BrokerFailureManager(failure_threshold=1)
    manager.register_broker("coinbase", 0.50)
    manager.register_broker("kraken", 0.30)
    manager.register_broker("okx", 0.20)

    assert manager.record_error("coinbase", "provider_down") is True
    weights = manager.get_active_allocation_weights()

    assert weights == {"kraken": 0.30, "okx": 0.20}
    assert sum(weights.values()) == 0.50
    assert manager.get_status()["coinbase"]["capital_redistributed"] is False


def test_strategy_selection_is_thread_local():
    selector = BrokerStrategySelector()
    barrier = threading.Barrier(2)

    def choose(name: str):
        selected = selector.select_strategy(name)
        barrier.wait(timeout=5)
        return name, selector.current_broker, selected

    with ThreadPoolExecutor(max_workers=2) as pool:
        kraken_future = pool.submit(choose, "kraken")
        coinbase_future = pool.submit(choose, "coinbase")
        kraken_name, kraken_current, kraken_config = kraken_future.result(timeout=10)
        coinbase_name, coinbase_current, coinbase_config = coinbase_future.result(timeout=10)

    assert kraken_name == kraken_current == "kraken"
    assert coinbase_name == coinbase_current == "coinbase"
    assert kraken_config is selector.get_config("kraken")
    assert coinbase_config is selector.get_config("coinbase")
    assert selector.get_config("okx") is not None
    assert selector.get_config("alpaca") is not None


def test_strategy_selector_compatibility_printer_still_exists(capsys):
    selector = BrokerStrategySelector()
    selector.print_strategy_comparison()
    assert "BROKER STRATEGY COMPARISON" in capsys.readouterr().out


def test_same_broker_different_accounts_get_distinct_runtime_state(monkeypatch):
    class FakeExecutionEngine:
        def __init__(self, broker_client):
            self.broker_client = broker_client

    class FakeApex:
        def __init__(self, broker_client=None, config=None):
            self.broker_client = broker_client
            self.config = config or {}
            self.execution_engine = FakeExecutionEngine(broker_client)

    class FakeCoreLoop:
        def __init__(self, apex_strategy, max_positions=5):
            self.apex = apex_strategy
            self.max_positions = max_positions
            self._zero_signal_streak = 0

    fake_apex_module = types.ModuleType("bot.nija_apex_strategy_v71")
    fake_apex_module.NIJAApexStrategyV71 = FakeApex
    fake_core_module = types.ModuleType("bot.nija_core_loop")
    fake_core_module.NijaCoreLoop = FakeCoreLoop
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", fake_apex_module)
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", fake_core_module)

    class BrokerType:
        value = "kraken"

    class Broker:
        broker_type = BrokerType()

        def __init__(self, account_id):
            self.account_id = account_id

    owner = types.SimpleNamespace(
        broker=None,
        independent_trader=object(),
        symbols=["BTC-USD"],
        _symbols_by_broker={"kraken": ["BTC-USD"]},
        _symbol_scan_cursor={"kraken": 0},
        failed_brokers={},
        _wiring_recovery_lock=threading.Lock(),
        _heartbeat_trade_lock=threading.Lock(),
        _symbol_universe_lock=threading.Lock(),
        _heartbeat_trade_enabled=True,
        _heartbeat_trade_thread=object(),
        _heartbeat_trade_completed=True,
        _heartbeat_trade_success=True,
    )

    manager = BrokerCellRuntimeManager()
    account_a = manager.get_or_create(owner, Broker("acct-a"))
    account_b = manager.get_or_create(owner, Broker("acct-b"))

    assert account_a.key == ("kraken", "acct-a")
    assert account_b.key == ("kraken", "acct-b")
    assert account_a.strategy is not account_b.strategy
    assert account_a.apex is not account_b.apex
    assert account_a.core_loop is not account_b.core_loop
    assert account_a.strategy._symbols_by_broker is not account_b.strategy._symbols_by_broker
    assert account_a.strategy._symbol_scan_cursor is not account_b.strategy._symbol_scan_cursor
    assert account_a.strategy.failed_brokers is not account_b.strategy.failed_brokers
    assert account_a.strategy._heartbeat_trade_enabled is False
    assert account_b.strategy._heartbeat_trade_enabled is False

    account_a.core_loop._zero_signal_streak = 9
    account_a.strategy._symbol_scan_cursor["kraken"] = 7
    assert account_b.core_loop._zero_signal_streak == 0
    assert account_b.strategy._symbol_scan_cursor["kraken"] == 0
