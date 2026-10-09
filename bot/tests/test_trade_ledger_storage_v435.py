"""Offline storage evidence checks; do not assert durability from a local DB."""
from __future__ import annotations

from bot.runtime_trade_ledger_storage_v435 import inspect_ledger_storage
from bot.trade_ledger_db import TradeLedgerDB
from bot.confirmed_performance_report import get_confirmed_performance_report


def test_render_overlay_is_not_durable_even_if_file_exists(tmp_path):
    path = tmp_path / "data" / "trade_ledger.db"
    evidence = inspect_ledger_storage(path, mount_rows=[("/", "overlay")])
    assert evidence["state"] == "ephemeral_filesystem"
    assert evidence["dedicated_mount_detected"] is False
    assert evidence["ready_for_historical_pnl_certification"] is False
    assert evidence["backup_restore_verified"] is False


def test_separate_mount_is_observational_not_migration_or_backup_proof(tmp_path):
    mount = tmp_path / "persistent"
    db = mount / "trade_ledger.db"
    status = inspect_ledger_storage(
        db, mount_rows=[("/", "overlay"), (str(mount), "ext4")],
    )
    assert status["dedicated_mount_detected"] is True
    assert status["state"] == "dedicated_mount_detected_migration_and_backup_unverified"
    assert status["restart_persistence_verified"] is False
    assert status["migration_integrity_verified"] is False
    assert status["backup_restore_verified"] is False


def test_mount_evidence_absent_does_not_invent_persistence(tmp_path):
    outcome = inspect_ledger_storage(tmp_path / "test.db", mount_rows=[])
    assert outcome["state"] == "mount_evidence_unavailable"
    assert outcome["ready_for_historical_pnl_certification"] is False


def test_confirmed_performance_reports_pending_and_unverified_storage(tmp_path):
    ledger = TradeLedgerDB(str(tmp_path / "trade_ledger.db"))
    result = get_confirmed_performance_report(
        ledger, broker="kraken", user_id="platform",
    )
    assert result["historical_ledger_durability_verified"] is False
    assert result["historical_fill_reconciliation_complete"] is False
    assert result["pending_confirmed_closes"] == 0
    assert result["ledger_storage_evidence"]["backup_restore_verified"] is False
    assert result["overall"]["trades"] == 0
