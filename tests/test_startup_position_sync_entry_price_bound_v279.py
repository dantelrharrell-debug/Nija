"""Regression coverage for authoritative startup position reconciliation v279."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import bot.startup_position_sync as sync


class _Tracker:
    def __init__(self, *, verified: bool = True, exact_sync: bool = True) -> None:
        self.positions = {}
        self.verified = verified
        if not exact_sync:
            self.sync_position_snapshot = None

    def get_all_positions(self):
        return list(self.positions.values())

    def get_position(self, symbol):
        return self.positions.get(symbol)

    def sync_position_snapshot(self, **kwargs):
        symbol = kwargs["symbol"]
        entry = float(kwargs.get("entry_price") or 0.0)
        verified = bool(self.verified and entry > 0)
        self.positions[symbol] = {
            "symbol": symbol,
            "quantity": kwargs["quantity"],
            "entry_price": entry,
            "size_usd": kwargs.get("size_usd", 0.0),
            "cost_basis_verified": verified,
            "auto_exit_blocked": not verified,
        }
        return True

    def track_entry(self, **kwargs):
        self.positions[kwargs["symbol"]] = {
            "symbol": kwargs["symbol"],
            "quantity": kwargs["quantity"],
            "entry_price": kwargs["entry_price"],
            "size_usd": kwargs["size_usd"],
            "cost_basis_verified": kwargs["entry_price"] > 0,
            "auto_exit_blocked": kwargs["entry_price"] <= 0,
        }
        return True


class _Broker:
    connected = True

    def __init__(self, positions, *, tracker=None, entry_price=100.0):
        self.position_tracker = tracker or _Tracker()
        self._positions = positions
        self.entry_price = entry_price
        self.entry_calls = 0

    def get_positions(self):
        return self._positions

    def get_real_entry_price(self, symbol):
        self.entry_calls += 1
        return self.entry_price


def _position(symbol="BTC-USD"):
    return {
        "symbol": symbol,
        "quantity": 0.01,
        "current_price": 120.0,
        "size_usd": 1.2,
    }


def test_explicit_empty_list_is_authoritative_empty_snapshot() -> None:
    broker = _Broker([])
    assert sync._adopt_broker_positions(broker, "platform:test", None) == 0
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == tuple()


def test_non_list_snapshot_fails_closed_instead_of_becoming_empty() -> None:
    broker = _Broker({"positions": []})
    assert sync._adopt_broker_positions(broker, "platform:test", None) == 0
    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_symbols == tuple()


def test_unverified_cost_basis_does_not_mark_broker_adopted(monkeypatch) -> None:
    tracker = _Tracker(verified=False)
    broker = _Broker([_position()], tracker=tracker, entry_price=0.0)
    monkeypatch.setattr(sync, "_bounded_real_entry_price", lambda *_: (0.0, "api_timeout"))
    assert sync._adopt_broker_positions(broker, "platform:test", None) == 0
    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_symbols == tuple()
    assert tracker.get_position("BTC-USD")["auto_exit_blocked"] is True


def test_verified_cost_basis_for_every_position_marks_broker_adopted(monkeypatch) -> None:
    broker = _Broker([_position("BTC-USD"), _position("ETH-USD")])
    monkeypatch.setattr(sync, "_bounded_real_entry_price", lambda *_: (100.0, "api"))
    assert sync._adopt_broker_positions(broker, "platform:test", None) == 2
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == ("BTC-USD", "ETH-USD")


def test_missing_exact_sync_never_uses_current_market_price(monkeypatch) -> None:
    tracker = _Tracker(exact_sync=False)
    broker = _Broker([_position()], tracker=tracker, entry_price=0.0)
    monkeypatch.setattr(sync, "_bounded_real_entry_price", lambda *_: (0.0, "api_timeout"))
    assert sync._adopt_broker_positions(broker, "platform:test", None) == 0
    assert broker._startup_position_sync_adopted is False
    assert tracker.get_position("BTC-USD") is None


def test_bounded_entry_price_timeout_is_single_flight(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    class SlowBroker:
        def __init__(self):
            self.calls = 0

        def get_real_entry_price(self, symbol):
            self.calls += 1
            started.set()
            release.wait(timeout=2.0)
            return 99.0

    broker = SlowBroker()
    monkeypatch.setenv("NIJA_POSITION_ENTRY_PRICE_TIMEOUT_S", "0.25")
    sync._ENTRY_PRICE_FLIGHTS.clear()
    try:
        first_started = time.monotonic()
        price, source = sync._bounded_real_entry_price(broker, "BTC-USD")
        elapsed = time.monotonic() - first_started
        assert started.is_set()
        assert price == 0.0
        assert source == "api_timeout"
        assert elapsed < 1.0
        assert broker.calls == 1

        price2, source2 = sync._bounded_real_entry_price(broker, "BTC-USD")
        assert price2 == 0.0
        assert source2 == "api_timeout"
        assert broker.calls == 1

        release.set()
        time.sleep(0.05)
        price3, source3 = sync._bounded_real_entry_price(broker, "BTC-USD")
        assert price3 == 99.0
        assert source3 == "api"
        assert broker.calls == 1
    finally:
        release.set()
        sync._ENTRY_PRICE_FLIGHTS.clear()
