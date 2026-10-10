"""Strictly synthetic NIJA persistence-audit regressions; never access a broker."""
from __future__ import annotations
import json
import sqlite3
from scripts.nija_state_store_persistence_audit_v441 import inspect, _inventory


def fixture(tmp_path):
    root = tmp_path / "persistent"
    positions, prices = root / "positions", root / "entry_prices"
    positions.mkdir(parents=True)
    prices.mkdir()
    ledger = root / "trade_ledger.db"
    with sqlite3.connect(ledger) as conn:
        conn.execute("CREATE TABLE synthetic_only (id INTEGER PRIMARY KEY)")
    return root, ledger, positions, prices


def audit(root, ledger, positions, prices, **kwargs):
    return inspect(root, ledger, positions, prices, mounts=[(root, "ext4")], **kwargs)


def test_ephemeral_account_state_fails_closed_without_moving_source(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    old = tmp_path / "app" / "data"
    (old / "positions").mkdir(parents=True)
    (old / "entry_prices").mkdir()
    source = old / "positions" / "platform__kraken.json"
    source.write_text('{"positions":{"FOO":{"quantity":1}}}')
    before = source.read_bytes()
    report = audit(root, ledger, old / "positions", old / "entry_prices", legacy_root=old)
    assert report["status"] == "STORAGE_PATHS_OUTSIDE_PERSISTENT_DISK"
    assert not report["storage_paths_aligned"]
    assert report["files_written_or_copied"] is False
    assert report["eligible_for_24h_observation"] is False
    assert source.read_bytes() == before


def test_valid_paths_do_not_certify_history_or_trading(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    report = audit(root, ledger, positions, prices)
    assert report["status"] == "PATHS_AND_FILES_PRESENT_HISTORY_NOT_CERTIFIED"
    assert report["storage_paths_aligned"]
    for key in ("sqlite_integrity_verified", "off_host_backup_verified",
                "isolated_restore_verified", "historical_entries_verified",
                "strategy_pnl_verified", "execution_authorized",
                "eligible_for_24h_observation"):
        assert report[key] is False


def test_missing_or_overlay_mount_not_persistent(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    for mounts in ([], [(root, "overlay")], [(root, "tmpfs")]):
        report = inspect(root, ledger, positions, prices, mounts=mounts)
        assert report["status"] == "DEDICATED_MOUNT_UNVERIFIED"
        assert not report["storage_paths_aligned"]


def test_symlink_escape_rejected(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "position_link"
    link.symlink_to(outside, target_is_directory=True)
    report = audit(root, ledger, link, prices)
    assert report["status"] == "STORAGE_PATHS_OUTSIDE_PERSISTENT_DISK"
    assert report["account_store_inventories"]["account_positions"]["state"] == "symlink_directory_rejected"


def test_non_json_directory_entry_is_not_clean_inventory(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    (positions / "notes.txt").write_text("synthetic")
    report = audit(root, ledger, positions, prices)
    assert report["status"] == "ACCOUNT_STORE_FILES_UNVERIFIED"
    assert not report["storage_paths_aligned"]


def test_missing_ledger_not_misreported_as_aligned(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    ledger.unlink()
    report = audit(root, ledger, positions, prices)
    assert report["status"] == "TRADING_LEDGER_FILE_UNVERIFIED"
    assert report["trading_ledger_file_state"] == "ledger_file_missing"
    assert not report["storage_paths_aligned"]


def test_invalid_sqlite_header_not_accepted(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    ledger.write_bytes(b"not a SQLite ledger")
    report = audit(root, ledger, positions, prices)
    assert report["status"] == "TRADING_LEDGER_FILE_UNVERIFIED"
    assert not report["storage_paths_aligned"]


def test_symlink_ledger_rejected(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    alias = root / "alias.db"
    alias.symlink_to(ledger)
    report = audit(root, alias, positions, prices)
    assert report["trading_ledger_file_state"] == "symlink_ledger_rejected"
    assert not report["storage_paths_aligned"]


def test_missing_account_store_directory_rejected(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    prices.rmdir()
    report = audit(root, ledger, positions, prices)
    assert report["status"] == "ACCOUNT_STORE_FILES_UNVERIFIED"
    assert not report["storage_paths_aligned"]


def test_malformed_or_array_json_rejected(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    file = positions / "platform__kraken.json"
    for raw in ("not json", "[]"):
        file.write_text(raw)
        report = audit(root, ledger, positions, prices)
        assert report["status"] == "ACCOUNT_STORE_FILES_UNVERIFIED"
        assert not report["storage_paths_aligned"]


def legacy_dirs(tmp_path):
    old = tmp_path / "app_data"
    (old / "positions").mkdir(parents=True)
    (old / "entry_prices").mkdir()
    return old


def test_legacy_to_empty_store_requires_reconciliation(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    old = legacy_dirs(tmp_path)
    (old / "positions" / "platform__kraken.json").write_text('{"positions":{"XBT":{"quantity":1}}}')
    report = audit(root, ledger, positions, prices, legacy_root=old)
    assert report["status"] == "LEGACY_ACCOUNT_STATE_RECONCILIATION_REQUIRED"
    assert report["possible_unmigrated_legacy_state"]
    assert not report["storage_paths_aligned"]


def test_legacy_same_filename_different_content_is_not_preserved(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    old = legacy_dirs(tmp_path)
    filename = "platform__kraken.json"
    (old / "positions" / filename).write_text('{"positions":{"XBT":{"quantity":1}}}')
    (positions / filename).write_text('{"positions":{"XBT":{"quantity":2}}}')
    report = audit(root, ledger, positions, prices, legacy_root=old)
    assert report["status"] == "LEGACY_ACCOUNT_STATE_RECONCILIATION_REQUIRED"
    assert report["possible_unmigrated_legacy_state"]
    assert not report["storage_paths_aligned"]


def test_matching_legacy_hash_only_proves_byte_identity(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    old = legacy_dirs(tmp_path)
    filename = "platform__kraken.json"
    raw = json.dumps({"positions": {"XBT": {"quantity": 1}}})
    (old / "positions" / filename).write_text(raw)
    (positions / filename).write_text(raw)
    report = audit(root, ledger, positions, prices, legacy_root=old)
    assert report["status"] == "PATHS_AND_FILES_PRESENT_HISTORY_NOT_CERTIFIED"
    assert report["storage_paths_aligned"]
    assert report["historical_entries_verified"] is False
    assert report["eligible_for_24h_observation"] is False


def test_unreadable_legacy_inventory_is_blocker(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    old = legacy_dirs(tmp_path)
    (old / "positions" / "platform__kraken.json").write_text("{broken")
    report = audit(root, ledger, positions, prices, legacy_root=old)
    assert report["status"] == "LEGACY_ACCOUNT_STATE_INVENTORY_UNVERIFIED"
    assert report["legacy_inventory_unverified"]
    assert not report["storage_paths_aligned"]


def test_missing_legacy_source_not_a_restoration_claim(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    report = audit(root, ledger, positions, prices, legacy_root=tmp_path / "absent")
    assert report["status"] == "PATHS_AND_FILES_PRESENT_HISTORY_NOT_CERTIFIED"
    assert report["historical_entries_verified"] is False
    assert report["eligible_for_24h_observation"] is False


def test_inventory_never_outputs_raw_account_positions(tmp_path):
    root, ledger, positions, prices = fixture(tmp_path)
    token = "secret_synthetic_position_marker_only"
    (positions / "platform__kraken.json").write_text(json.dumps({"positions": {token: {"quantity": 1}}}))
    report = audit(root, ledger, positions, prices)
    assert token not in json.dumps(report)
    assert report["account_store_inventories"]["account_positions"]["files"] == 1
