from __future__ import annotations

import os

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
