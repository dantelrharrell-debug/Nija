"""Offline persistent-auth restart and SQLite restore rehearsal."""
import sqlite3

import pytest

from auth.email_service import EmailService
from auth.storage import auth_database_path
from auth.two_factor import TwoFactorAuth
from auth.user_database import UserDatabase


def test_all_auth_state_survives_restart_and_isolated_restore(tmp_path, monkeypatch):
    path = tmp_path / "mounted" / "users.db"
    path.parent.mkdir(mode=0o700)
    monkeypatch.setenv("NIJA_AUTH_USER_DB_PATH", str(path))
    users = UserDatabase()
    # Deliberately synthetic identity and password; no external services.
    assert users.create_user("offline-user", "offline@example.invalid", "offline-fixture")
    session_id = users.create_session("offline-user", "2099-01-01T00:00:00")
    assert session_id
    TwoFactorAuth()
    EmailService()
    with sqlite3.connect(path) as source:
        source.execute("INSERT INTO two_factor_auth (user_id, totp_secret, created_at) VALUES (?, ?, ?)",
                       ("offline-user", "offline-fixture", "2026-11-04"))
        source.commit()
        before = source.iterdump()
        snapshot = list(before)
        with sqlite3.connect(tmp_path / "isolated-restore.db") as restored:
            source.backup(restored)
            assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert list(restored.iterdump()) == snapshot
    restarted = UserDatabase()
    assert restarted.verify_password("offline-user", "offline-fixture")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT session_id FROM sessions").fetchone() == (session_id,)
        assert db.execute("SELECT enabled FROM two_factor_auth").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM email_verification_tokens").fetchone() == (0,)
    assert not (tmp_path / "users.db").exists()


def test_missing_mount_fails_without_creating_or_copying_state(tmp_path, monkeypatch):
    path = tmp_path / "missing-mount" / "users.db"
    monkeypatch.setenv("NIJA_AUTH_USER_DB_PATH", str(path))
    for factory in (UserDatabase, TwoFactorAuth, EmailService):
        with pytest.raises(sqlite3.OperationalError):
            factory()
    assert not path.parent.exists()


def test_explicit_legacy_path_is_preserved_and_empty_configuration_rejected(monkeypatch):
    monkeypatch.setenv("NIJA_AUTH_USER_DB_PATH", "/data/auth/users.db")
    assert auth_database_path("legacy.db") == "legacy.db"
    assert auth_database_path() == "/data/auth/users.db"
    monkeypatch.setenv("NIJA_AUTH_USER_DB_PATH", "")
    with pytest.raises(ValueError):
        auth_database_path()
