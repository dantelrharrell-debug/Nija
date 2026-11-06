"""Regress privilege escalation and disposable-storage startup fallbacks."""
from __future__ import annotations

from pathlib import Path
import os
from unittest.mock import Mock

import pytest

from game_sandbox import staging_bootstrap as bootstrap


@pytest.fixture
def private_disk(tmp_path, monkeypatch):
    """Model the already-provisioned mount; real writes still hit the filesystem."""
    tmp_path.chmod(0o700)
    uid = tmp_path.stat().st_uid
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: uid if uid else 10001)
    if uid == 0:
        # Root-only development environments may prohibit chown/setuid. Model
        # only ownership metadata here; hosted Docker tests exercise real UID.
        original_lstat = Path.lstat

        def unprivileged_metadata(path):
            fields = list(original_lstat(path))
            fields[4] = 10001
            return os.stat_result(fields)

        monkeypatch.setattr(Path, "lstat", unprivileged_metadata)
    monkeypatch.setattr(bootstrap.os.path, "ismount", lambda path: path == tmp_path)
    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("NIJA_IQ_SANDBOX_DATABASE", str(tmp_path / "trading_iq_sandbox.sqlite3"))
    return tmp_path


def test_root_is_denied_even_when_disabled(monkeypatch):
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "false")
    with pytest.raises(RuntimeError, match="non_root"):
        bootstrap.validate_runtime()


def test_disabled_non_root_health_does_not_require_payment_disk(monkeypatch):
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 10001)
    monkeypatch.setenv("NIJA_IQ_SANDBOX_ENABLED", "false")
    bootstrap.validate_runtime(Path("/does-not-exist"))


def test_private_disk_probe_never_creates_entitlement_database(private_disk):
    bootstrap.validate_runtime(private_disk)
    assert list(private_disk.iterdir()) == []


def test_missing_mount_never_falls_back_to_container_storage(private_disk, monkeypatch):
    monkeypatch.setattr(bootstrap.os.path, "ismount", lambda path: False)
    with pytest.raises(RuntimeError, match="persistent_mount"):
        bootstrap.validate_runtime(private_disk)


@pytest.mark.parametrize("mode", [0o755, 0o777, 0o750])
def test_shared_disk_permissions_are_denied(private_disk, mode):
    private_disk.chmod(mode)
    with pytest.raises(RuntimeError, match="private_disk_owner"):
        bootstrap.validate_runtime(private_disk)


def test_wrong_owner_is_denied(private_disk, monkeypatch):
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 12345)
    with pytest.raises(RuntimeError, match="private_disk_owner"):
        bootstrap.validate_runtime(private_disk)


def test_symlink_mount_is_denied(private_disk, monkeypatch):
    link = private_disk / "link"
    link.symlink_to(private_disk, target_is_directory=True)
    monkeypatch.setattr(bootstrap.os.path, "ismount", lambda path: True)
    monkeypatch.setenv("NIJA_IQ_SANDBOX_DATABASE", str(link / "trading_iq_sandbox.sqlite3"))
    with pytest.raises(RuntimeError, match="private_disk_owner"):
        bootstrap.validate_runtime(link)


def test_database_path_cannot_select_another_directory(private_disk, monkeypatch):
    monkeypatch.setenv("NIJA_IQ_SANDBOX_DATABASE", "/tmp/trading_iq_sandbox.sqlite3")
    with pytest.raises(RuntimeError, match="dedicated_disk_path"):
        bootstrap.validate_runtime(private_disk)


def test_read_only_mount_denies_startup_without_exec(private_disk, monkeypatch, capsys):
    validate = bootstrap.validate_runtime
    monkeypatch.setattr(bootstrap, "validate_runtime", lambda: validate(private_disk))
    monkeypatch.setattr(bootstrap.tempfile, "TemporaryFile", Mock(side_effect=OSError("private-detail")))
    execute = Mock()
    monkeypatch.setattr(bootstrap.os, "execv", execute)
    assert bootstrap.main() == 1
    execute.assert_not_called()
    assert "private-detail" not in capsys.readouterr().err


def test_valid_preflight_execs_single_gunicorn_process(monkeypatch):
    monkeypatch.setattr(bootstrap, "validate_runtime", Mock())
    execute = Mock(side_effect=SystemExit(0))
    monkeypatch.setattr(bootstrap.os, "execv", execute)
    monkeypatch.setenv("PORT", "10101")
    with pytest.raises(SystemExit):
        bootstrap.main()
    args = execute.call_args.args[1]
    assert args[1:3] == ["-m", "gunicorn"]
    assert args[args.index("--bind") + 1] == "0.0.0.0:10101"
    assert args[args.index("--workers") + 1] == "1"
