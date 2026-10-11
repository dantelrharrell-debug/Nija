"""Dante's owner authority and durable, explicitly delegated administrator access.

Authority comes from a verified login ID pinned in deployment configuration,
never a display name, email supplied by a client, broker role, or JWT role claim.
This module does not grant trading execution authority or change safety gates.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jwt


class AccessDenied(Exception):
    """An authentication, authorization, or authority-configuration denial."""

    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


def auth_database_path() -> str:
    """Return the database path shared with the existing login service."""
    return os.getenv("NIJA_AUTH_USER_DB_PATH", "users.db")


def _enabled_user(user_id: str) -> bool:
    try:
        uri = Path(auth_database_path()).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            row = connection.execute("SELECT enabled FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return bool(row and row[0] == 1)
    except sqlite3.Error as exc:
        raise AccessDenied("Authentication database unavailable", 503) from exc


def authenticate_bearer(header: str) -> str:
    """Verify an expiring login token and require a current enabled database user."""
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AccessDenied("Authentication required", 401)
    secret = os.getenv("JWT_SECRET_KEY", "")
    if len(secret) < 32:
        raise AccessDenied("Authentication is not configured", 503)
    try:
        payload = jwt.decode(
            parts[1], secret, algorithms=["HS256"],
            options={"require": ["exp", "iat", "user_id"]},
        )
    except jwt.InvalidTokenError as exc:
        raise AccessDenied("Invalid or expired login", 401) from exc
    user_id = payload["user_id"]
    if not isinstance(user_id, str) or not user_id or not _enabled_user(user_id):
        raise AccessDenied("Invalid or disabled login", 401)
    return user_id


def owner_user_id() -> str:
    """Return Dante's operator-pinned login ID; never infer it from a name."""
    owner = os.getenv("NIJA_OWNER_USER_ID", "").strip()
    if not owner:
        raise AccessDenied("Owner login identity is not configured", 503)
    return owner


def _admin_database_path() -> Path:
    return Path(os.getenv("NIJA_ADMIN_DB_PATH", str(Path(auth_database_path()).with_name("admin_permissions.db"))))


def is_owner(user_id: str) -> bool:
    """Check the pinned ID and enabled login account, without privilege aliases."""
    return user_id == owner_user_id() and _enabled_user(user_id)


def is_administrator(user_id: str) -> bool:
    """Check owner identity or an unrevoked grant issued by the current owner."""
    owner = owner_user_id()
    if not _enabled_user(user_id):
        return False
    if user_id == owner:
        return True
    path = _admin_database_path()
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            row = connection.execute(
                "SELECT granted_by FROM administrator_grants WHERE user_id = ?", (user_id,),
            ).fetchone()
            # Disabling the owner invalidates delegated authority too.
            return bool(row and row[0] == owner and _enabled_user(owner))
    except sqlite3.Error as exc:
        raise AccessDenied("Administrator permissions unavailable", 503) from exc


def require_administrator(user_id: str, owner_only: bool = False) -> None:
    """Deny requests without the required owner or explicitly granted role."""
    permitted = is_owner(user_id) if owner_only else is_administrator(user_id)
    if not permitted:
        raise AccessDenied("Owner authority required" if owner_only else "Administrator authority required")


def permission_summary(user_id: str) -> dict[str, Any]:
    """Return server-calculated permissions; client role claims are ignored."""
    owner = is_owner(user_id)
    admin = owner or is_administrator(user_id)
    return {
        "user_id": user_id,
        "display_name": "Dante" if owner else user_id,
        "role": "owner" if owner else "administrator" if admin else "user",
        "is_creator": owner,
        "is_master_user": owner,
        "is_administrator": admin,
        "can_manage_administrators": owner,
    }


def set_administrator(actor_id: str, target_id: str, grant: bool) -> None:
    """Persist a grant or revocation atomically; only Dante can delegate authority."""
    require_administrator(actor_id, owner_only=True)
    if not isinstance(target_id, str) or not target_id.strip() or len(target_id) > 256:
        raise AccessDenied("A valid login user ID is required", 400)
    if target_id == owner_user_id():
        raise AccessDenied("The owner role cannot be granted or revoked", 400)
    if grant and not _enabled_user(target_id):
        raise AccessDenied("Target login account must exist and be enabled", 400)
    path = _admin_database_path()
    # The operator must provision the directory; do not silently create a
    # transient substitute when the persistent mount is missing.
    if not path.parent.is_dir():
        raise AccessDenied("Administrator storage is not provisioned", 503)
    try:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with closing(sqlite3.connect(path, timeout=5)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS administrator_grants "
                "(user_id TEXT PRIMARY KEY, granted_by TEXT NOT NULL, granted_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS administrator_audit "
                "(id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL, target_id TEXT NOT NULL, "
                "action TEXT NOT NULL, recorded_at TEXT NOT NULL)"
            )
            now = datetime.now(timezone.utc).isoformat()
            if grant:
                connection.execute(
                    "INSERT INTO administrator_grants VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET granted_by=excluded.granted_by, granted_at=excluded.granted_at",
                    (target_id, actor_id, now),
                )
            else:
                connection.execute("DELETE FROM administrator_grants WHERE user_id = ?", (target_id,))
            connection.execute(
                "INSERT INTO administrator_audit (actor_id, target_id, action, recorded_at) VALUES (?, ?, ?, ?)",
                (actor_id, target_id, "grant" if grant else "revoke", now),
            )
    except (OSError, sqlite3.Error) as exc:
        raise AccessDenied("Administrator permission write failed", 503) from exc
