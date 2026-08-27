"""Persistent encrypted storage for mobile push-device registrations.

Push tokens are sensitive credentials. This store never logs plaintext tokens and
never returns them from normal list operations. Tokens are encrypted at rest with
a stable application secret supplied through PUSH_TOKEN_ENCRYPTION_KEY or
VAULT_ENCRYPTION_KEY.

The SQLite file location is configurable with MOBILE_DEVICE_DB_PATH. Production
deployments must place that path on durable storage (or replace this adapter with
a database-backed implementation that preserves the same interface).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken

from security.secrets_manager import get_secret

logger = logging.getLogger("nija.mobile_devices")

_ALLOWED_PLATFORMS = {"ios", "android"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MobileDeviceStore:
    """Thread-safe encrypted push-token registry persisted to SQLite."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.getenv("MOBILE_DEVICE_DB_PATH", "mobile_devices.db")
        self._write_lock = threading.RLock()
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mobile_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    push_token_encrypted TEXT NOT NULL,
                    push_token_hash TEXT NOT NULL,
                    device_info_json TEXT NOT NULL DEFAULT '{}',
                    registered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, device_id)
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_token_hash "
                "ON mobile_devices(push_token_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_devices_user "
                "ON mobile_devices(user_id)"
            )

    @staticmethod
    def _cipher() -> Fernet:
        secret = get_secret("PUSH_TOKEN_ENCRYPTION_KEY") or get_secret("VAULT_ENCRYPTION_KEY")
        if not secret:
            raise RuntimeError(
                "Push-token persistence requires PUSH_TOKEN_ENCRYPTION_KEY or "
                "VAULT_ENCRYPTION_KEY. Configure a stable secret before device registration."
            )

        raw = secret.encode("utf-8")
        # Accept a native Fernet key when one is supplied; otherwise derive a
        # stable Fernet key from the configured high-entropy application secret.
        try:
            return Fernet(raw)
        except (ValueError, TypeError):
            derived = hashlib.sha256(b"nija-push-token-v1:" + raw).digest()
            return Fernet(base64.urlsafe_b64encode(derived))

    @staticmethod
    def _token_hash(push_token: str) -> str:
        return hashlib.sha256(push_token.encode("utf-8")).hexdigest()

    @classmethod
    def _encrypt(cls, push_token: str) -> str:
        return cls._cipher().encrypt(push_token.encode("utf-8")).decode("ascii")

    @classmethod
    def _decrypt(cls, encrypted: str) -> str:
        try:
            return cls._cipher().decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(
                "Stored push token cannot be decrypted with the configured encryption key"
            ) from exc

    def register_device(
        self,
        user_id: str,
        device_id: str,
        platform: str,
        push_token: str,
        device_info: Optional[Dict] = None,
    ) -> None:
        user_id = str(user_id or "").strip()
        device_id = str(device_id or "").strip()
        platform = str(platform or "").strip().lower()
        push_token = str(push_token or "").strip()

        if not user_id or not device_id or not push_token:
            raise ValueError("user_id, device_id, and push_token are required")
        if platform not in _ALLOWED_PLATFORMS:
            raise ValueError("platform must be ios or android")
        if len(device_id) > 512 or len(push_token) > 8192:
            raise ValueError("device_id or push_token exceeds the allowed size")

        encrypted = self._encrypt(push_token)
        token_hash = self._token_hash(push_token)
        info_json = json.dumps(device_info or {}, separators=(",", ":"), sort_keys=True)
        now = _utcnow()

        with self._write_lock, self._connect() as conn:
            # Provider tokens can rotate or be reassigned after reinstall. A valid,
            # authenticated registration owns the presented token from this point.
            conn.execute(
                "DELETE FROM mobile_devices WHERE push_token_hash = ? "
                "AND NOT (user_id = ? AND device_id = ?)",
                (token_hash, user_id, device_id),
            )
            conn.execute(
                """
                INSERT INTO mobile_devices (
                    user_id, device_id, platform, push_token_encrypted,
                    push_token_hash, device_info_json, registered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, device_id) DO UPDATE SET
                    platform = excluded.platform,
                    push_token_encrypted = excluded.push_token_encrypted,
                    push_token_hash = excluded.push_token_hash,
                    device_info_json = excluded.device_info_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    device_id,
                    platform,
                    encrypted,
                    token_hash,
                    info_json,
                    now,
                    now,
                ),
            )

        logger.info("Mobile device registered user_id=%s device_id=%s platform=%s", user_id, device_id, platform)

    def unregister_device(self, user_id: str, device_id: str) -> bool:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM mobile_devices WHERE user_id = ? AND device_id = ?",
                (user_id, device_id),
            )
            deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Mobile device unregistered user_id=%s device_id=%s", user_id, device_id)
        return deleted

    def list_devices(self, user_id: str, include_tokens: bool = False) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT device_id, platform, push_token_encrypted, device_info_json,
                       registered_at, updated_at
                FROM mobile_devices
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()

        devices: List[Dict] = []
        for row in rows:
            try:
                device_info = json.loads(row["device_info_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                device_info = {}
            item = {
                "device_id": row["device_id"],
                "platform": row["platform"],
                "device_info": device_info,
                "registered_at": row["registered_at"],
                "updated_at": row["updated_at"],
            }
            if include_tokens:
                item["push_token"] = self._decrypt(row["push_token_encrypted"])
            devices.append(item)
        return devices

    def delete_user_devices(self, user_id: str) -> int:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM mobile_devices WHERE user_id = ?", (user_id,))
            deleted = max(cursor.rowcount, 0)
        if deleted:
            logger.info("Deleted %s mobile device registrations for user_id=%s", deleted, user_id)
        return deleted

    def count_devices(self, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM mobile_devices WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["count"] if row else 0)


_store: Optional[MobileDeviceStore] = None
_store_lock = threading.Lock()


def get_mobile_device_store(db_path: Optional[str] = None) -> MobileDeviceStore:
    global _store
    if db_path is not None:
        return MobileDeviceStore(db_path=db_path)
    with _store_lock:
        if _store is None:
            _store = MobileDeviceStore()
        return _store


__all__ = ["MobileDeviceStore", "get_mobile_device_store"]
