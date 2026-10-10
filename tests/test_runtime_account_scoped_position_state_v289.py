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


def test_cleanup_scoping_ready_cannot_certify_quantity_disagreement(tmp_path, monkeypatch):
    from bot import runtime_all_account_position_exit_coverage_v281_patch as v281
    from bot import runtime_authoritative_position_coverage_v285_patch as v285
    from bot.position_tracker import PositionTracker

    monkeypatch.setenv("NIJA_ACCOUNT_POSITION_STATE_DIR", str(tmp_path / "positions"))
    monkeypatch.setenv("NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR", str(tmp_path / "entries"))
    tracker = PositionTracker(storage_file=str(tmp_path / "legacy.json"))
    tracker.positions = {
        "TEST-USD": {"quantity": 2.0, "entry_price": 100.0, "cost_basis_verified": True,
                     "auto_exit_blocked": False},
        "STALE-USD": {"quantity": 1.0},
    }
    broker = SimpleNamespace(
        connected=True, broker_type="kraken", account_type="platform", position_tracker=tracker,
        _startup_position_sync_fetch_ok=True, _startup_position_sync_adopted=True,
        _startup_position_sync_symbols=("TEST-USD",),
    )
    assert v285._record_snapshot_success(broker, [{"symbol": "TEST-USD", "quantity": 1.0, "entry_price": 100.0}])
    for name in ("_patch_position_tracker_constructor", "_patch_broker_constructors",
                 "_patch_startup_adopter", "_stop_legacy_global_repair"):
        monkeypatch.setattr(v289, name, lambda: True)
    monkeypatch.setattr(v289, "_expected_accounts", lambda: {"platform:kraken": broker})
    scoped = v289.reconcile_once()
    assert scoped["ready"] is True
    assert scoped["cleanup"]["platform:kraken"] == (1, "authoritative_cleanup_complete")
    assert scoped["protection_certified"] is False
    assert scoped["persistence_certified"] is False
    assert tracker.positions["TEST-USD"]["quantity"] == 2.0
    original = v281._account_audit
    monkeypatch.setattr(v281, "_account_audit", original)
    assert v285._patch_v281_account_audit()
    manager = SimpleNamespace(_platform_brokers={"kraken": broker})
    result = v281.evaluate(manager, structural_exit_ready=True)
    assert result["ready"] is False
    assert any("reconciliation_quantity_mismatch" in reason for reason in result["pending"]["platform:kraken"])
    assert all(row["protective_exit_verified"] is False for row in result["positions"])
    # Simulate legacy state repopulation after cleanup; no blind second deletion.
    tracker.positions["STALE-USD"] = {"quantity": 1.0}
    result = v281.evaluate(manager, structural_exit_ready=True)
    assert result["ready"] is False
    assert "STALE-USD" in tracker.positions
