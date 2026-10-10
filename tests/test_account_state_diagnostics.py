import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.account_state_diagnostics import log_tracker_read
from scripts import nija_account_state_diagnostics as diagnostics


@pytest.fixture
def state(tmp_path, monkeypatch):
    positions, entries, disk = (tmp_path / name for name in ("positions", "entries", "disk"))
    for root in (positions, entries, disk):
        root.mkdir()
    name = "platform__kraken.json"
    row = {"quantity": 1.0, "entry_price": 100.0, "entry_price_source": "execution",
           "cost_basis_verified": True}
    (positions / name).write_text(json.dumps({"positions": {"TEST-USD": row}}))
    (entries / name).write_text(json.dumps({
        "TEST-USD": {"quantity": 1.0, "price": 100.0, "source": "execution"}
    }))
    ledger = disk / "ledger.db"
    ledger.write_bytes(b"opaque-ledger-evidence")
    wal = Path(str(ledger) + "-wal")
    wal.write_bytes(b"opaque-wal-evidence")
    mounts = tmp_path / "mountinfo"
    mounts.write_text("36 25 8:1 / /data rw - ext4 /dev/disk rw\n")
    for key in ("NIJA_ACCOUNT_POSITION_STATE_DIR", "NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR"):
        monkeypatch.delenv(key, raising=False)
    real_inventory = diagnostics.inventory

    def test_inventory(*args, **kwargs):
        result = real_inventory(positions, entries, disk, mounts, (ledger,))
        # Only mount/path validation is simulated; never write to /data.
        result["roots"]["disk"] = "/data"
        return result

    monkeypatch.setattr(diagnostics, "inventory", test_inventory)
    manifest = test_inventory()
    return SimpleNamespace(positions=positions, entries=entries, disk=disk, wal=wal,
                           mounts=mounts, manifest=manifest, scopes={name: "platform__kraken"},
                           inventory=real_inventory, name=name)


def test_inventory_is_content_free_and_byte_preserving(state):
    before = {p: p.read_bytes() for root in (state.positions, state.entries, state.disk) for p in root.iterdir()}
    report = state.inventory(state.positions, state.entries, state.disk, state.mounts)
    assert "TEST-USD" not in json.dumps(report)
    assert all(len(row["sha256"]) == 64 and row["bytes"] > 0 for row in report["files"])
    assert report["observation_allowed"] is False
    assert before == {path: path.read_bytes() for path in before}


def test_dry_run_never_certifies_or_writes(state):
    report = diagnostics.dry_run(state.manifest, state.scopes, "review-ticket", state.mounts)
    assert len(report["planned"]) == 2
    assert all(row["destination"].startswith("/data/") for row in report["planned"])
    assert report["mutations_performed"] is False
    assert all(value is False for key, value in report.items() if key.endswith("_verified"))
    assert report["observation_allowed"] is False


@pytest.mark.parametrize("scope", [None, "user__unknown__kraken", "user__a__b__kraken", "platform__unknown"])
def test_missing_ambiguous_scope_rejected(state, scope):
    with pytest.raises(ValueError, match="account_scope"):
        diagnostics.dry_run(state.manifest, {state.name: scope}, "review", state.mounts)


def test_empty_migration_rejected(state):
    (state.positions / state.name).unlink()
    (state.entries / state.name).unlink()
    manifest = diagnostics.inventory()
    with pytest.raises(ValueError, match="empty_migration"):
        diagnostics.dry_run(manifest, {}, "review", state.mounts)


@pytest.mark.parametrize("change", ["checksum", "wal", "missing_wal"])
def test_manifest_and_wal_mismatch_rejected(state, change):
    if change == "checksum":
        (state.positions / state.name).write_text("{}")
    elif change == "wal":
        state.wal.write_bytes(b"different-wal")
    else:
        state.wal.unlink()
    with pytest.raises(ValueError, match="checksum_or_file_set_mismatch_including_wal"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)


@pytest.mark.parametrize("payload,reason", [
    ('{"positions":{"TEST-USD":{},"TEST-USD":{}}}', "duplicate_json_key"),
    ('{"positions":{"TEST-USD":{},"TEST/USD":{}}}', "untrusted_cost_basis"),
    ('{"positions":{"TEST-USD":{"quantity":1,"entry_price":100,'
     '"entry_price_source":"estimated","cost_basis_verified":true}}}', "untrusted_cost_basis"),
])
def test_duplicate_and_untrusted_records_rejected(state, payload, reason):
    (state.positions / state.name).write_text(payload)
    manifest = diagnostics.inventory()
    with pytest.raises(ValueError, match=reason):
        diagnostics.dry_run(manifest, state.scopes, "review", state.mounts)


def test_normalized_duplicate_symbol_rejected(state):
    row = {"quantity": 1, "entry_price": 100, "entry_price_source": "execution", "cost_basis_verified": True}
    (state.positions / state.name).write_text(json.dumps({"positions": {"TEST-USD": row, "TEST/USD": row}}))
    with pytest.raises(ValueError, match="duplicate_or_missing_symbol"):
        diagnostics.dry_run(diagnostics.inventory(), state.scopes, "review", state.mounts)


def test_symlink_and_parent_symlink_rejected(state, tmp_path):
    link = state.positions / "unexpected.json"
    link.symlink_to(state.entries / state.name)
    with pytest.raises(ValueError, match="unexpected_symlink"):
        state.inventory(state.positions, state.entries, state.disk, state.mounts)
    parent = tmp_path / "linked"
    parent.symlink_to(state.entries, target_is_directory=True)
    with pytest.raises(ValueError, match="unexpected_symlink"):
        diagnostics._fingerprint(parent / state.name)


def test_collisions_and_path_scope_mixups_rejected(state, monkeypatch):
    original = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: str(path) == "/data/positions/" + state.name or original(path))
    with pytest.raises(ValueError, match="destination_collision"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)
    monkeypatch.setenv("NIJA_ACCOUNT_POSITION_STATE_DIR", "/app/data/positions")
    with pytest.raises(ValueError, match="configured_state_path"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)


def test_existing_non_directory_target_rejected(state, monkeypatch):
    original_exists = Path.exists
    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "exists", lambda path: str(path) == "/data/positions" or original_exists(path))
    monkeypatch.setattr(Path, "is_dir", lambda path: False if str(path) == "/data/positions" else original_is_dir(path))
    with pytest.raises(ValueError, match="destination_directory_collision"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)


@pytest.mark.parametrize("nested", [False, True])
def test_directory_traversal_errors_fail_closed(state, monkeypatch, nested):
    blocked = state.positions / "nested" if nested else state.positions
    if nested:
        blocked.mkdir()
    original = diagnostics.os.scandir

    def unreadable(path):
        if Path(path) == blocked:
            raise PermissionError("unreadable inventory directory")
        return original(path)

    monkeypatch.setattr(diagnostics.os, "scandir", unreadable)
    with pytest.raises(PermissionError):
        state.inventory(state.positions, state.entries, state.disk, state.mounts)


def test_unmounted_data_and_missing_review_rejected(state, monkeypatch):
    with pytest.raises(ValueError, match="backup_review"):
        diagnostics.dry_run(state.manifest, state.scopes, "", state.mounts)
    state.manifest["mounts"] = []
    monkeypatch.setattr(diagnostics, "inventory", lambda *args: state.manifest)
    with pytest.raises(ValueError, match="persistent_data_mount"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)


def test_ephemeral_mount_rejected(state, monkeypatch):
    state.manifest["mounts"][0]["filesystem"] = "tmpfs"
    monkeypatch.setattr(diagnostics, "inventory", lambda *args: state.manifest)
    with pytest.raises(ValueError, match="persistent_data_mount"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)


def test_added_wal_and_missing_entry_scope_rejected(state):
    Path(str(state.wal) + "-journal").write_bytes(b"not-part-of-reviewed-inventory")
    with pytest.raises(ValueError, match="checksum_or_file_set_mismatch"):
        diagnostics.dry_run(state.manifest, state.scopes, "review", state.mounts)
    (state.entries / state.name).unlink()
    with pytest.raises(ValueError, match="missing_or_ambiguous_account_scope"):
        diagnostics.dry_run(diagnostics.inventory(), state.scopes, "review", state.mounts)


def test_tracker_log_correlates_identity_without_private_contents(caplog):
    private_quantity = 987654321.123456
    store = SimpleNamespace(_data_file="/app/data/entry_prices/user__private_account__kraken.json")
    tracker = SimpleNamespace(storage_file="/app/data/positions/user__private_account__kraken.json",
                              _eps=store, _nija_account_scope_v289="user__private_account__kraken",
                              positions={"PRIVATE-SYMBOL": {"quantity": private_quantity}})
    with caplog.at_level("INFO", logger="nija.account_state_diagnostics"):
        for point in ("v289_cleanup", "v281_holdings", "v285_snapshot_comparison", "position_tracker_load"):
            log_tracker_read(tracker, point)
    assert caplog.text.count(hex(id(tracker))) == 4
    assert caplog.text.count(hex(id(store))) == 4
    assert "private_account" not in caplog.text
    assert "PRIVATE-SYMBOL" not in caplog.text
    assert str(private_quantity) not in caplog.text
    assert "storage_directory=/app/data/positions" in caplog.text


def test_tracker_log_suppresses_unchanged_reads_but_logs_changes_and_loads(caplog):
    store = SimpleNamespace(_data_file="/app/data/entry_prices/platform__kraken.json")
    tracker = SimpleNamespace(storage_file="/app/data/positions/platform__kraken.json",
                              _eps=store, _nija_account_scope_v289="platform__kraken")
    with caplog.at_level("INFO", logger="nija.account_state_diagnostics"):
        log_tracker_read(tracker, "v285_snapshot_comparison")
        log_tracker_read(tracker, "v285_snapshot_comparison")
        tracker.storage_file = "/data/positions/platform__kraken.json"
        log_tracker_read(tracker, "v285_snapshot_comparison")
        tracker._eps = SimpleNamespace(_data_file="/app/data/entry_prices/platform__kraken.json")
        log_tracker_read(tracker, "v285_snapshot_comparison")
        log_tracker_read(tracker, "position_tracker_load", force=True)
        log_tracker_read(tracker, "position_tracker_load", force=True)
    assert caplog.text.count("point=v285_snapshot_comparison") == 3
    assert caplog.text.count("point=position_tracker_load") == 2


@pytest.mark.parametrize(
    "error, expected_code",
    [("checksum_or_file_set_mismatch_including_wal", "checksum_or_file_set_mismatch_including_wal"),
     ("destination_collision_no_overwrite", "destination_collision_no_overwrite"),
     ("sensitive exception details", "unexpected_error")],
)
def test_cli_exposes_only_safe_error_codes(monkeypatch, capsys, error, expected_code):
    import sys

    monkeypatch.setattr(sys, "argv", ["nija_account_state_diagnostics"])

    def fail(*args, **kwargs):
        raise ValueError(error)

    monkeypatch.setattr(diagnostics, "inventory", fail)
    assert diagnostics.main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["error_code"] == expected_code
    if expected_code == "unexpected_error":
        assert error not in json.dumps(output)
