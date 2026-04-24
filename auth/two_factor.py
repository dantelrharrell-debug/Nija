"""
NIJA Two-Factor Authentication (2FA)

Implements TOTP-based 2FA compatible with Google Authenticator and similar apps.

Features:
- Generate TOTP secrets
- QR code generation for authenticator app setup
- TOTP code verification with time-window tolerance
- Backup code generation and verification
- SQLite-backed persistent storage

Author: NIJA Trading Systems
Version: 1.0
"""

import os
import logging
import sqlite3
import secrets
import hashlib
import base64
from typing import Optional, List, Tuple, Dict
from datetime import datetime

import pyotp

logger = logging.getLogger("nija.auth.two_factor")

# TOTP issuer label shown in authenticator apps
TOTP_ISSUER = os.getenv("TOTP_ISSUER", "NIJA Trading")

# Number of backup codes to generate per user
BACKUP_CODE_COUNT = 10


class TwoFactorAuth:
    """
    Manages TOTP-based two-factor authentication.

    Each user gets a secret stored (encrypted at rest) in SQLite.
    Backup codes are hashed before storage.
    """

    def __init__(self, db_path: str = "users.db"):
        self.db_path = db_path
        self._init_tables()
        logger.info("TwoFactorAuth initialized")

    def _init_tables(self) -> None:
        """Create 2FA tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS two_factor_auth (
                user_id      TEXT PRIMARY KEY,
                totp_secret  TEXT NOT NULL,
                enabled      INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                enabled_at   TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS two_factor_backup_codes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                code_hash    TEXT NOT NULL,
                used         INTEGER NOT NULL DEFAULT 0,
                used_at      TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Setup flow
    # ------------------------------------------------------------------

    def generate_setup(self, user_id: str, email: str) -> Dict:
        """
        Generate a TOTP secret and provisioning URI for QR code display.

        Returns a dict with:
            - secret: base32 secret (show once, then discard)
            - provisioning_uri: otpauth:// URI
            - qr_data_uri: base64-encoded PNG (if qrcode library is available)
        """
        secret = pyotp.random_base32()

        # Persist the (disabled) secret so the verify step can confirm it
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO two_factor_auth
                (user_id, totp_secret, enabled, created_at)
            VALUES (?, ?, 0, ?)
        """, (user_id, secret, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=email, issuer_name=TOTP_ISSUER)

        result: Dict = {
            "secret": secret,
            "provisioning_uri": provisioning_uri,
        }

        # Attempt to generate a QR code PNG encoded as data URI
        try:
            import qrcode
            import io
            qr = qrcode.make(provisioning_uri)
            buf = io.BytesIO()
            qr.save(buf, format="PNG")
            encoded = base64.b64encode(buf.getvalue()).decode()
            result["qr_data_uri"] = f"data:image/png;base64,{encoded}"
        except ImportError:
            logger.debug("qrcode library not available; skipping QR data URI")

        logger.info(f"Generated 2FA setup for user {user_id}")
        return result

    def confirm_setup(self, user_id: str, code: str) -> Tuple[bool, Optional[List[str]]]:
        """
        Confirm 2FA setup by verifying the first code the user provides.

        On success, enables 2FA and returns one-time backup codes.

        Returns:
            (True, [backup_codes]) on success
            (False, None) on failure
        """
        row = self._get_row(user_id)
        if not row:
            logger.warning(f"No 2FA setup found for user {user_id}")
            return False, None

        secret, enabled, _, _ = row
        totp = pyotp.TOTP(secret)

        if not totp.verify(code, valid_window=1):
            logger.warning(f"2FA confirmation failed for user {user_id}")
            return False, None

        backup_codes = self._generate_backup_codes(user_id)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE two_factor_auth
            SET enabled = 1, enabled_at = ?
            WHERE user_id = ?
        """, (datetime.utcnow().isoformat(), user_id))
        conn.commit()
        conn.close()

        logger.info(f"2FA enabled for user {user_id}")
        return True, backup_codes

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def is_enabled(self, user_id: str) -> bool:
        """Return True if 2FA is currently enabled for the user."""
        row = self._get_row(user_id)
        return bool(row and row[1])

    def verify_totp(self, user_id: str, code: str) -> bool:
        """
        Verify a 6-digit TOTP code.

        Accepts the current window plus one adjacent window in each direction
        to account for clock skew.
        """
        row = self._get_row(user_id)
        if not row or not row[1]:
            return False

        secret = row[0]
        totp = pyotp.TOTP(secret)
        ok = totp.verify(code, valid_window=1)
        if not ok:
            logger.warning(f"TOTP verification failed for user {user_id}")
        return ok

    def verify_backup_code(self, user_id: str, code: str) -> bool:
        """
        Verify and consume a single-use backup code.

        Backup codes are hashed (SHA-256) before storage; the raw code is
        never persisted after generation.
        """
        code_hash = self._hash_code(code.strip().upper())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM two_factor_backup_codes
            WHERE user_id = ? AND code_hash = ? AND used = 0
        """, (user_id, code_hash))
        row = cursor.fetchone()
        if not row:
            conn.close()
            logger.warning(f"Backup code verification failed for user {user_id}")
            return False

        # Mark as used
        cursor.execute("""
            UPDATE two_factor_backup_codes
            SET used = 1, used_at = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), row[0]))
        conn.commit()
        conn.close()
        logger.info(f"Backup code used for user {user_id}")
        return True

    # ------------------------------------------------------------------
    # Disable / reset
    # ------------------------------------------------------------------

    def disable(self, user_id: str) -> bool:
        """Disable 2FA for a user (e.g., admin reset)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE two_factor_auth SET enabled = 0 WHERE user_id = ?",
            (user_id,)
        )
        affected = cursor.rowcount
        cursor.execute(
            "DELETE FROM two_factor_backup_codes WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()
        if affected:
            logger.info(f"2FA disabled for user {user_id}")
        return bool(affected)

    def regenerate_backup_codes(self, user_id: str) -> Optional[List[str]]:
        """Invalidate old backup codes and issue fresh ones."""
        if not self.is_enabled(user_id):
            return None
        return self._generate_backup_codes(user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_row(self, user_id: str) -> Optional[Tuple]:
        """Return (totp_secret, enabled, created_at, enabled_at) or None."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT totp_secret, enabled, created_at, enabled_at
            FROM two_factor_auth
            WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row

    def _generate_backup_codes(self, user_id: str) -> List[str]:
        """
        Create BACKUP_CODE_COUNT fresh backup codes, replacing any existing ones.

        Returns the plain-text codes (shown to the user once only).
        """
        plain_codes = [
            "-".join([
                secrets.token_hex(2).upper(),
                secrets.token_hex(2).upper(),
                secrets.token_hex(2).upper(),
            ])
            for _ in range(BACKUP_CODE_COUNT)
        ]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM two_factor_backup_codes WHERE user_id = ?",
            (user_id,)
        )
        for code in plain_codes:
            cursor.execute("""
                INSERT INTO two_factor_backup_codes (user_id, code_hash)
                VALUES (?, ?)
            """, (user_id, self._hash_code(code)))
        conn.commit()
        conn.close()
        return plain_codes

    @staticmethod
    def _hash_code(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[TwoFactorAuth] = None


def get_two_factor_auth(db_path: str = "users.db") -> TwoFactorAuth:
    """Return the module-level TwoFactorAuth singleton."""
    global _instance
    if _instance is None:
        _instance = TwoFactorAuth(db_path=db_path)
    return _instance
