from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_execution_terminal_recovery_v342_patch as v342


class _Broker:
    def __init__(self, name: str, balance: float, required: float = 5.0) -> None:
        self.broker_type = SimpleNamespace(value=name)
        self._last_known_balance = balance
        self.required = required
        self.calls = []

    def place_market_order(self, symbol, side, quantity, size_type="quote"):
        self.calls.append((symbol, side, quantity, size_type))
        return {
            "status": "filled",
            "order_id": "ord-1",
            "filled_price": 100.0,
            "filled_size_usd": float(quantity) * 100.0 if size_type == "base" else float(quantity),
        }


class _Strategy:
    def __init__(self, brokers, selected) -> None:
        self._brokers = brokers
        self.selected = selected
        self.broker = selected
        self.broker_manager = SimpleNamespace(active_broker=selected)

    def _select_entry_broker(self, candidates):
        for broker in candidates.values():
            return broker, str(getattr(getattr(broker, "broker_type", None), "value", "")), "ok"
        return None, "", "none"

    def _resolve_heartbeat_trade_amount_usd(self, broker):
        return broker.required


class _V274:
    @staticmethod
    def _broker_key(strategy, broker):
        return broker.broker_type.value

    @staticmethod
    def _heartbeat_required_notional(strategy, broker):
        return strategy._resolve_heartbeat_trade_amount_usd(broker)

    @staticmethod
    def _cached_entry_balance(strategy, broker, broker_key):
        return broker._last_known_balance, "broker_cache"

    @staticmethod
    def _candidate_brokers(strategy):
        return strategy._brokers


def test_underfunded_selected_heartbeat_venue_switches_to_funded_ready_venue(monkeypatch):
    coinbase = _Broker("coinbase", 3.32)
    kraken = _Broker("kraken", 125.0)
    strategy = _Strategy({"coinbase": coinbase, "kraken": kraken}, coinbase)
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "coinbase,kraken")
    monkeypatch.setattr(v342, "_heartbeat_scope", lambda: True)

    wrapped = v342._wrap_heartbeat_selector(lambda self: coinbase, _V274)
    selected = wrapped(strategy)

    assert selected is kraken
    assert strategy.broker is kraken
    assert strategy.broker_manager.active_broker is kraken


def test_funded_selected_heartbeat_venue_is_preserved(monkeypatch):
    coinbase = _Broker("coinbase", 25.0)
    kraken = _Broker("kraken", 125.0)
    strategy = _Strategy({"coinbase": coinbase, "kraken": kraken}, coinbase)
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "coinbase,kraken")
    monkeypatch.setattr(v342, "_heartbeat_scope", lambda: True)

    wrapped = v342._wrap_heartbeat_selector(lambda self: coinbase, _V274)
    assert wrapped(strategy) is coinbase


def test_heartbeat_selection_fails_closed_when_no_ready_venue_is_funded(monkeypatch):
    coinbase = _Broker("coinbase", 3.0)
    kraken = _Broker("kraken", 4.0)
    strategy = _Strategy({"coinbase": coinbase, "kraken": kraken}, coinbase)
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "coinbase,kraken")
    monkeypatch.setattr(v342, "_heartbeat_scope", lambda: True)

    wrapped = v342._wrap_heartbeat_selector(lambda self: coinbase, _V274)
    assert wrapped(strategy) is None


def test_canonical_protective_close_uses_verified_base_quantity(monkeypatch):
    broker = _Broker("coinbase", 100.0)

    class _V328:
        @staticmethod
        def _submit_direct(*args, **kwargs):
            raise AssertionError("ordinary quote terminal must not be used for canonical protective close")

    monkeypatch.setattr(v342.importlib, "import_module", lambda name: _V328 if name == "bot.runtime_confirmed_fill_profitability_v328_patch" else __import__(name))
    assert v342._patch_protective_exit_base_terminal()

    result = _V328._submit_direct(
        broker,
        "ETH-USD",
        "sell",
        15.0,
        {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
            "verified_position_quantity": 0.20,
            "price_hint_usd": 100.0,
        },
    )

    assert result["status"] == "filled"
    assert broker.calls == [("ETH-USD", "sell", 0.15, "base")]


def test_ordinary_order_keeps_existing_terminal_semantics(monkeypatch):
    broker = _Broker("coinbase", 100.0)
    calls = []

    class _V328:
        @staticmethod
        def _submit_direct(broker_obj, symbol, side, size_usd, metadata):
            calls.append((broker_obj, symbol, side, size_usd, dict(metadata)))
            return {"status": "filled", "order_id": "ordinary", "filled_price": 100.0, "filled_size_usd": size_usd}

    monkeypatch.setattr(v342.importlib, "import_module", lambda name: _V328 if name == "bot.runtime_confirmed_fill_profitability_v328_patch" else __import__(name))
    assert v342._patch_protective_exit_base_terminal()

    _V328._submit_direct(broker, "BTC-USD", "buy", 5.0, {})
    assert calls == [(broker, "BTC-USD", "buy", 5.0, {})]
