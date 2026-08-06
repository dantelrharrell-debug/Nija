from types import SimpleNamespace

from bot.trading_strategy import TradingStrategy


class DummyApex:
    def __init__(self):
        self._last_account_balance = 25.0
        self.execution_engine = SimpleNamespace(get_all_positions=lambda: {})
        self.updated_broker = None

    def update_broker_client(self, broker):
        self.updated_broker = broker


class DummyCoreLoop:
    def __init__(self):
        self.calls = []

    def run_scan_phase(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            symbols_scored=1,
            entries_taken=0,
            entries_blocked=0,
            exits_taken=0,
            next_interval=7,
        )


class DummyBroker:
    connected = True

    def get_account_balance(self):
        return {"total_balance": 25.0}


def _strategy_for_run_cycle():
    strategy = TradingStrategy.__new__(TradingStrategy)
    strategy.apex = DummyApex()
    strategy.nija_core_loop = DummyCoreLoop()
    strategy.broker = None
    strategy.symbols = ["BTC/USD"]
    strategy.execution_engine = strategy.apex.execution_engine
    strategy._ensure_nija_wiring = lambda: None
    strategy._maybe_refresh_symbols = lambda force=False: None
    strategy._get_active_broker = lambda: (_ for _ in ()).throw(AssertionError("should not select a different broker"))
    return strategy


def test_run_cycle_accepts_caller_broker_and_passes_user_mode():
    strategy = _strategy_for_run_cycle()
    broker = DummyBroker()

    next_interval = strategy.run_cycle(broker=broker, user_mode=True)

    assert next_interval == 7
    assert strategy.broker is broker
    assert strategy.apex.updated_broker is broker
    assert strategy.nija_core_loop.calls[0]["broker"] is broker
    assert strategy.nija_core_loop.calls[0]["user_mode"] is True


def test_run_cycle_without_broker_preserves_active_broker_selection():
    strategy = _strategy_for_run_cycle()
    broker = DummyBroker()
    strategy._get_active_broker = lambda: broker

    strategy.run_cycle()

    assert strategy.nija_core_loop.calls[0]["broker"] is broker
    assert strategy.nija_core_loop.calls[0]["user_mode"] is False


def test_run_cycle_logs_zero_trade_diagnostic(caplog):
    strategy = _strategy_for_run_cycle()
    broker = DummyBroker()

    strategy.nija_core_loop.run_scan_phase = lambda **kwargs: SimpleNamespace(
        symbols_scored=4,
        entries_taken=0,
        entries_blocked=0,
        exits_taken=0,
        next_interval=11,
        candidates_selected=0,
        candidates_volume_blocked=3,
        candidates_terminal_risk_blocked=1,
        candidates_order_ready=0,
        orders_submitted=0,
        broker_acks=0,
        fills=0,
        execute_successes=0,
        gate_rejections={"volume_gate_rejected": 3, "risk_gate_rejected": 1},
        errors=[],
    )

    with caplog.at_level("CRITICAL", logger="nija.trading_strategy"):
        next_interval = strategy.run_cycle(broker=broker)

    assert next_interval == 11
    assert "RUN_CYCLE_SCAN_DIAGNOSTIC" in caplog.text
    assert "outcome=no_candidates_selected" in caplog.text
    assert "reason=volume_gate_rejected" in caplog.text
    assert "gate_summary=risk_gate_rejected:1,volume_gate_rejected:3" in caplog.text
