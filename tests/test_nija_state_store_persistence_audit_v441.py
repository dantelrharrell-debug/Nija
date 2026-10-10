"""Read-only tests with synthetic filesystem evidence; no live accounts."""
from pathlib import Path

from scripts.nija_state_store_persistence_audit_v441 import inspect, _inventory


def test_separate_app_state_never_claims_persistence(tmp_path):
    durable = tmp_path / "data"
    durable.mkdir()
    app = tmp_path / "app" / "data"
    (app / "positions").mkdir(parents=True)
    (app / "entry_prices").mkdir(parents=True)
    sample = app / "positions" / "user__sample__kraken.json"
    sample.write_text('{"only_test":1}')
    before = sample.read_bytes()
    result = inspect(durable, durable / "trade_ledger.db", app / "positions", app / "entry_prices", mounts=[(durable, "ext4")], legacy_root=app)
    assert result["dedicated_mount_observed"]
    assert result["status"] == "STORAGE_PATHS_OUTSIDE_PERSISTENT_DISK"
    assert not result["storage_paths_aligned"]
    assert result["optional_legacy_inventories"]["account_positions"]["files"] == 1
    assert result["eligible_for_24h_observation"] is False
    assert sample.read_bytes() == before


def test_aligned_paths_still_cannot_certify_history(tmp_path):
    durable = tmp_path / "data"
    positions, prices = durable / "positions", durable / "entry_prices"
    positions.mkdir(parents=True)
    prices.mkdir()
    (durable / "trade_ledger.db").write_bytes(b"not a real SQLite ledger")
    result = inspect(durable, durable / "trade_ledger.db", positions, prices, mounts=[(durable, "ext4")])
    assert result["storage_paths_aligned"]
    assert result["status"] == "PATHS_ALIGNED_HISTORY_NOT_CERTIFIED"
    assert not result["ledger_integrity_verified"]
    assert not result["off_host_backup_verified"]
    assert not result["eligible_for_24h_observation"]


def test_missing_mount_never_claims_durability(tmp_path):
    data = tmp_path / "data"
    (data / "positions").mkdir(parents=True)
    (data / "entry_prices").mkdir()
    result = inspect(data, data / "trade_ledger.db", data / "positions", data / "entry_prices", mounts=[])
    assert result["status"] == "DEDICATED_MOUNT_UNVERIFIED"
    assert not result["storage_paths_aligned"]


def test_symlink_escape_fails_closed(tmp_path):
    data = tmp_path / "data"
    other = tmp_path / "ephemeral"
    data.mkdir()
    other.mkdir()
    (data / "positions").symlink_to(other, target_is_directory=True)
    (data / "entry_prices").mkdir()
    result = inspect(data, data / "trade_ledger.db", data / "positions", data / "entry_prices", mounts=[(data, "ext4")])
    assert result["status"] == "STORAGE_PATHS_OUTSIDE_PERSISTENT_DISK"
    assert result["account_store_inventories"]["account_positions"]["state"] == "symlink_directory_rejected"


def test_unexpected_files_do_not_pass_inventory(tmp_path):
    directory = tmp_path / "positions"
    directory.mkdir()
    (directory / "unexpected.txt").write_text("test")
    assert _inventory(directory)["stable"] is False
