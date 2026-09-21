from __future__ import annotations

import os
from types import SimpleNamespace

from bot import runtime_account_scoped_position_state_v289_patch as v289


def test_scope_isolates_platform_and_users():
    assert v289._scope("platform", None, "coinbase") == "platform__coinbase"
    assert v289._scope("user", "daivon_frazier", "kraken") == "user__daivon_frazier__kraken"
    assert v289._scope("user", "tania_gilbert", "kraken") == "user__tania_gilbert__kraken"


def test_scoped_paths_do_not_share_files(tmp_path, monkeypatch):
    monkeypatch.setenv("NIJA_ACCOUNT_POSITION_STATE_DIR", str(tmp_path / "positions"))
    monkeypatch.setenv("NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR", str(tmp_path / "entries"))
    a = v289._position_file("platform__coinbase")
    b = v289._position_file("user__daivon_frazier__kraken")
    ea = v289._entry_file("platform__coinbase")
    eb = v289._entry_file("user__daivon_frazier__kraken")
    assert a != b
    assert ea != eb
    assert os.path.basename(a) == "platform__coinbase.json"


def test_local_tracker_binding_redirects_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("NIJA_ACCOUNT_POSITION_STATE_DIR", str(tmp_path / "positions"))
    monkeypatch.setenv("NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR", str(tmp_path / "entries"))
    from bot.position_tracker import PositionTracker

    tracker = PositionTracker(storage_file=str(tmp_path / "legacy.json"))
    assert v289._bind_tracker_instance(tracker, "platform__coinbase") is True
    assert tracker.storage_file == v289._position_file("platform__coinbase")
    assert getattr(tracker, "_nija_account_scope_v289") == "platform__coinbase"
    assert getattr(tracker, "_nija_account_entry_store_v289") is not None


class _Tracker:
    def __init__(self, positions):
        self.positions = dict(positions)
        self.last_rows = None

    def sync_with_broker(self, rows):
        self.last_rows = list(rows)
        broker_symbols = {
            str(row.get("symbol") or "").strip()
            for row in self.last_rows
            if isinstance(row, dict) and row.get("symbol")
        }
        missing = set(self.positions) - broker_symbols
        for symbol in missing:
            self.positions.pop(symbol, None)
        return len(missing)


def test_authoritative_zero_quantity_rows_remove_tracker_ghosts(monkeypatch):
    tracker = _Tracker({
        "BTC-USD": {"quantity": 8.0022066e-09},
        "ETH-USD": {"quantity": 2.179976761e-07},
        "ORCA-USD": {"quantity": 3.00125809},
    })
    broker = SimpleNamespace(
        position_tracker=tracker,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
    )
    monkeypatch.setattr(
        v289,
        "_current_snapshot_rows",
        lambda _broker: (
            True,
            (
                {"symbol": "BTC-USD", "quantity": 0.0},
                {"symbol": "ETH-USD", "quantity": 0.0},
                {"symbol": "ORCA-USD", "quantity": 3.00125809},
            ),
            "authoritative_position_snapshot_current",
        ),
    )

    removed, reason = v289._clean_authoritative_orphans(broker, "platform__kraken")

    assert reason == "authoritative_cleanup_complete"
    assert removed == 2
    assert set(tracker.positions) == {"ORCA-USD"}
    assert tracker.last_rows == [{"symbol": "ORCA-USD", "quantity": 3.00125809}]


def test_authoritative_positive_dust_is_preserved(monkeypatch):
    tracker = _Tracker({"BTC-USD": {"quantity": 8.0022066e-09}})
    broker = SimpleNamespace(
        position_tracker=tracker,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
    )
    monkeypatch.setattr(
        v289,
        "_current_snapshot_rows",
        lambda _broker: (
            True,
            ({"symbol": "BTC-USD", "quantity": 8.0022066e-09},),
            "authoritative_position_snapshot_current",
        ),
    )

    removed, reason = v289._clean_authoritative_orphans(broker, "platform__okx")

    assert reason == "authoritative_cleanup_complete"
    assert removed == 0
    assert set(tracker.positions) == {"BTC-USD"}
