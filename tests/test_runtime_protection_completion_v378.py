from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from bot import runtime_protection_completion_v378_patch as v378


class Tracker:
    def __init__(self, rows):
        self.rows = dict(rows)

    def get_all_positions(self):
        return list(self.rows)

    def get_position(self, symbol):
        return self.rows.get(symbol)

    def track_exit(self, symbol, exit_quantity=None):
        if symbol not in self.rows:
            return False
        del self.rows[symbol]
        return True


class Broker(SimpleNamespace):
    pass


def _install_fake_modules(monkeypatch, broker, snapshot_rows, *, wall=1000.0):
    manager = object()
    v281 = ModuleType("bot.runtime_all_account_position_exit_coverage_v281_patch")
    v281._canonical_manager = lambda: manager
    v281._expected_accounts = lambda _manager: {"platform:coinbase": broker}
    v281.evaluate = lambda _manager: {
        "positions": (),
        "pending": {},
        "ready": True,
    }
    v285 = ModuleType("bot.runtime_authoritative_position_coverage_v285_patch")
    v285._snapshot_status = lambda _broker: (True, "current", tuple(snapshot_rows), 1.0, 7)
    monkeypatch.setitem(sys.modules, v281.__name__, v281)
    monkeypatch.setitem(sys.modules, v285.__name__, v285)
    broker._nija_authoritative_position_snapshot_at_wall_v285 = wall


def test_coinbase_stale_tracker_removed_only_after_fresh_authoritative_absence(monkeypatch):
    tracker = Tracker({
        "ETH-USD": {
            "symbol": "ETH-USD",
            "quantity": 0.00000151,
            "last_entry_time": "1970-01-01T00:10:00+00:00",
        },
        "BTC-USD": {
            "symbol": "BTC-USD",
            "quantity": 0.001,
            "last_entry_time": "1970-01-01T00:10:00+00:00",
        },
    })
    broker = Broker(
        connected=True,
        position_tracker=tracker,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
    )
    _install_fake_modules(monkeypatch, broker, [{"symbol": "BTC-USD", "quantity": 0.001}])

    result = v378._coinbase_stale_tracker_reconcile()

    assert result["ready"] is True
    assert tracker.get_position("ETH-USD") is None
    assert tracker.get_position("BTC-USD") is not None
    assert any("ETH-USD" in item for item in result["removed"])


def test_coinbase_tracker_row_newer_than_snapshot_is_never_deleted(monkeypatch):
    tracker = Tracker({
        "ETH-USD": {
            "symbol": "ETH-USD",
            "quantity": 0.1,
            "last_entry_time": "1970-01-01T00:20:00+00:00",
        }
    })
    broker = Broker(
        connected=True,
        position_tracker=tracker,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
    )
    _install_fake_modules(monkeypatch, broker, [], wall=1000.0)

    result = v378._coinbase_stale_tracker_reconcile()

    assert result["ready"] is False
    assert tracker.get_position("ETH-USD") is not None
    assert any("row_newer_than_snapshot" in item for item in result["deferred"])


def test_native_backup_never_infers_capability_from_generic_place_order(monkeypatch):
    manager = object()
    generic = Broker(connected=True, place_order=lambda *a, **k: None)
    explicit = Broker(connected=True, ensure_native_protective_orders=lambda *a, **k: None)
    v281 = ModuleType("bot.runtime_all_account_position_exit_coverage_v281_patch")
    v281._canonical_manager = lambda: manager
    v281._expected_accounts = lambda _manager: {
        "platform:kraken": generic,
        "user:test:coinbase": explicit,
    }
    monkeypatch.setitem(sys.modules, v281.__name__, v281)

    result = v378._native_backup_capability()

    assert "platform:kraken" in result["software_fallback"]
    assert "user:test:coinbase" in result["supported"]
