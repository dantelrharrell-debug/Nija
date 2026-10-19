"""Non-authorizing diagnostics for account-state paths on and off the persistent root."""
import logging
from types import SimpleNamespace

from bot.account_state_diagnostics import _path_within_persistent_root, log_tracker_read


def test_persistent_root_requires_path_containment(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    assert _path_within_persistent_root(str(root / "positions" / "account.json"), str(root))
    assert not _path_within_persistent_root(str(tmp_path / "database" / "account.json"), str(root))
    assert not _path_within_persistent_root("", str(root))
    assert not _path_within_persistent_root(str(root) + "-other/account.json", str(root))


def test_symlink_escape_is_not_counted_as_persistent(tmp_path):
    root = tmp_path / "data"
    outside = tmp_path / "ephemeral"
    root.mkdir()
    outside.mkdir()
    (root / "redirect").symlink_to(outside, target_is_directory=True)
    assert not _path_within_persistent_root(str(root / "redirect" / "state.json"), str(root))


def test_diagnostics_flag_ephemeral_paths_without_account_contents(caplog):
    store = SimpleNamespace(_data_file="/app/data/entry_prices/user__secret_account__kraken.json")
    tracker = SimpleNamespace(
        storage_file="/app/data/positions/user__secret_account__kraken.json",
        _eps=store,
        _nija_account_scope_v289="user__secret_account__kraken",
        positions={"SECRET-SYMBOL": {"quantity": 123456789.5}},
    )
    with caplog.at_level(logging.INFO, logger="nija.account_state_diagnostics"):
        log_tracker_read(tracker, "persistent_root_regression", force=True)
    assert "storage_on_persistent_root=false" in caplog.text
    assert "entry_on_persistent_root=false" in caplog.text
    assert "persistence_verified=false" in caplog.text
    assert "secret_account" not in caplog.text
    assert "SECRET-SYMBOL" not in caplog.text
    assert "123456789.5" not in caplog.text


def test_diagnostics_never_certify_persistence_when_paths_are_on_disk(caplog):
    store = SimpleNamespace(_data_file="/data/entry_prices/platform__kraken.json")
    tracker = SimpleNamespace(
        storage_file="/data/positions/platform__kraken.json",
        _eps=store,
        _nija_account_scope_v289="platform__kraken",
    )
    with caplog.at_level(logging.INFO, logger="nija.account_state_diagnostics"):
        log_tracker_read(tracker, "persistent_root_on_disk", force=True)
    assert "storage_on_persistent_root=true" in caplog.text
    assert "entry_on_persistent_root=true" in caplog.text
    assert "persistence_verified=false" in caplog.text
