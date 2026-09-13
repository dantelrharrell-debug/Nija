from __future__ import annotations

import sys
import threading
import types
import time
from datetime import datetime, timezone

from bot import runtime_confirmed_fill_settlement_v415_patch as v415


def _confirmed_position(*, seconds_old: float = 0.0) -> dict:
    ts = datetime.fromtimestamp(time.time() - seconds_old, tz=timezone.utc).isoformat()
    return {
        "entry_price": 77000.0,
        "quantity": 0.00016,
        "size_usd": 12.32,
        "first_entry_time": ts,
        "last_entry_time": ts,
        "strategy": "HEARTBEAT_TRADE",
        "position_source": "nija_strategy",
        "entry_price_source": "execution",
        "cost_basis_verified": True,
    }


def test_confirmed_execution_classifier_and_age():
    position = _confirmed_position(seconds_old=3.0)
    assert v415._confirmed_execution_position(position) is True
    age = v415._position_age_seconds(position)
    assert 2.0 <= age <= 10.0


def test_position_tracker_preserves_fresh_confirmed_fill_then_removes_after_repeated_old_absence(monkeypatch):
    fake_module = types.ModuleType("bot.position_tracker")

    class FakeTracker:
        def __init__(self):
            self.lock = threading.Lock()
            self.positions = {"BTC-USD": _confirmed_position(seconds_old=0.0)}
            self.saved = 0

        def _save_positions(self):
            self.saved += 1

        def sync_with_broker(self, broker_positions):
            broker_symbols = {row["symbol"] for row in broker_positions}
            missing = set(self.positions) - broker_symbols
            for symbol in missing:
                self.positions.pop(symbol, None)
            return len(missing)

    fake_module.PositionTracker = FakeTracker
    monkeypatch.setitem(sys.modules, "bot.position_tracker", fake_module)
    monkeypatch.setenv("NIJA_CONFIRMED_FILL_SETTLEMENT_GRACE_SECONDS", "15")
    monkeypatch.setenv("NIJA_CONFIRMED_FILL_ORPHAN_MISSES_REQUIRED", "2")

    assert v415._patch_position_tracker() is True
    tracker = FakeTracker()

    # A broker snapshot racing immediately after a confirmed fill must not erase it.
    assert tracker.sync_with_broker([]) == 0
    assert "BTC-USD" in tracker.positions

    # Even repeated misses inside the bounded grace still preserve the fill.
    assert tracker.sync_with_broker([]) == 0
    assert "BTC-USD" in tracker.positions

    # Once the fill is old, the already-repeated authoritative absence can remove it.
    tracker.positions["BTC-USD"]["last_entry_time"] = datetime.fromtimestamp(
        time.time() - 60.0, tz=timezone.utc
    ).isoformat()
    assert tracker.sync_with_broker([]) == 1
    assert "BTC-USD" not in tracker.positions
    assert tracker.saved == 1


def test_position_tracker_clears_miss_counter_when_broker_position_reappears(monkeypatch):
    fake_module = types.ModuleType("bot.position_tracker")

    class FakeTracker:
        def __init__(self):
            self.lock = threading.Lock()
            self.positions = {"BTC-USD": _confirmed_position(seconds_old=60.0)}

        def _save_positions(self):
            pass

        def sync_with_broker(self, broker_positions):
            return 0

    fake_module.PositionTracker = FakeTracker
    monkeypatch.setitem(sys.modules, "bot.position_tracker", fake_module)
    monkeypatch.setenv("NIJA_CONFIRMED_FILL_ORPHAN_MISSES_REQUIRED", "2")

    assert v415._patch_position_tracker() is True
    tracker = FakeTracker()
    assert tracker.sync_with_broker([]) == 0
    assert tracker._nija_v415_orphan_miss_counts["BTC-USD"] == 1

    assert tracker.sync_with_broker([{"symbol": "BTC-USD", "quantity": 0.00016}]) == 0
    assert "BTC-USD" not in tracker._nija_v415_orphan_miss_counts

    # A new absence starts again at miss 1 instead of deleting immediately.
    assert tracker.sync_with_broker([]) == 0
    assert "BTC-USD" in tracker.positions


def test_heartbeat_buy_blocked_when_existing_authoritative_position(monkeypatch):
    fake_strategy = types.ModuleType("bot.trading_strategy")
    calls = []

    def original_submit(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "filled"}

    fake_strategy.submit_market_order_via_pipeline = original_submit
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", fake_strategy)

    fake_kill = types.ModuleType("bot.kill_switch")

    class ClearSwitch:
        def is_active(self):
            return False

    fake_kill.get_kill_switch = lambda: ClearSwitch()
    monkeypatch.setitem(sys.modules, "bot.kill_switch", fake_kill)

    class Broker:
        def get_positions(self):
            return [{"symbol": "BTC-USD", "quantity": 0.00016}]

        def get_open_orders(self):
            return []

    assert v415._patch_heartbeat_submit() is True
    result = fake_strategy.submit_market_order_via_pipeline(
        broker=Broker(),
        symbol="BTC-USD",
        side="buy",
        quantity=12.5,
        size_type="quote",
        strategy="HEARTBEAT_TRADE",
    )
    assert result["status"] == "error"
    assert "existing_position" in result["error"]
    assert calls == []


def test_heartbeat_buy_blocked_when_kill_switch_active(monkeypatch):
    fake_strategy = types.ModuleType("bot.trading_strategy")
    calls = []

    def original_submit(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "filled"}

    fake_strategy.submit_market_order_via_pipeline = original_submit
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", fake_strategy)

    fake_kill = types.ModuleType("bot.kill_switch")

    class ActiveSwitch:
        def is_active(self):
            return True

    fake_kill.get_kill_switch = lambda: ActiveSwitch()
    monkeypatch.setitem(sys.modules, "bot.kill_switch", fake_kill)

    class Broker:
        def get_positions(self):
            raise AssertionError("position read should not run while kill switch is active")

    assert v415._patch_heartbeat_submit() is True
    result = fake_strategy.submit_market_order_via_pipeline(
        broker=Broker(),
        symbol="BTC-USD",
        side="buy",
        quantity=12.5,
        size_type="quote",
        strategy="HEARTBEAT_TRADE",
    )
    assert result["status"] == "error"
    assert "kill_switch_not_clear" in result["error"]
    assert calls == []


def test_non_heartbeat_order_dispatch_is_unchanged(monkeypatch):
    fake_strategy = types.ModuleType("bot.trading_strategy")
    calls = []

    def original_submit(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "filled", "order_id": "ordinary-order"}

    fake_strategy.submit_market_order_via_pipeline = original_submit
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", fake_strategy)

    assert v415._patch_heartbeat_submit() is True
    result = fake_strategy.submit_market_order_via_pipeline(
        broker=object(),
        symbol="ETH-USD",
        side="buy",
        quantity=25.0,
        size_type="quote",
        strategy="APEX_v7.1",
    )
    assert result["status"] == "filled"
    assert result["order_id"] == "ordinary-order"
    assert len(calls) == 1
