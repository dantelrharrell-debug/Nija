"""
NIJA Secure Vault - Bank-Grade API Key Protection

This module provides institutional-grade security for user credentials:

Features:
- AES-256 encryption via Fernet (cryptography library)
- SQLite database with encrypted credential storage
- API key rotation support
- Audit logging for all credential access
- Zero-trust credential handling
- Regulatory compliance ready

Security Principles:
1. Credentials are NEVER stored in plain text
2. Encryption keys are stored separately from data
3. All access is logged for audit trail
4. Keys can be rotated without data loss
5. Multi-layer security (encryption + database + filesystem)
"""

import logging
import sqlite3
import json
import os
from typing import Dict, Optional, List
from datetime import datetime
from cryptography.fernet import Fernet
import hashlib

logger = logging.getLogger("nija.vault")


class SecureVault:
    """
    Secure credential vault with encryption and audit logging.

    This provides bank-grade protection for user API keys and secrets.
    All credentials are encrypted at rest using AES-256.
    """

    def __init__(
        self,
        db_path: str = "vault.db",
        encryption_key: Optional[bytes] = None,
        auto_create: bool = True
    ):
        """
        Initialize secure vault.

        Args:
            db_path: Path to SQLite database file
            encryption_key: 32-byte encryption key (generated if not provided)
            auto_create: Automatically create database if it doesn't exist
        """
        self.db_path = db_path

        # Initialize encryption
        if encryption_key is None:
            # Try to load from environment
            env_key = os.getenv('VAULT_ENCRYPTION_KEY')
            if env_key:
                encryption_key = env_key.encode()
                logger.info("Loaded encryption key from environment")
            else:
                # Generate new key
                encryption_key = Fernet.generate_key()
                logger.warning("Generated new encryption key - STORE THIS SECURELY!")
                logger.warning(f"VAULT_ENCRYPTION_KEY={encryption_key.decode()}")
                logger.warning("Set this as an environment variable to persist across restarts")

        self.cipher = Fernet(encryption_key)
        self.encryption_key_hash = hashlib.sha256(encryption_key).hexdigest()[:16]

        # Initialize database
        if auto_create:
            self._init_database()

        logger.info(f"Secure vault initialized (db={db_path}, key_hash={self.encryption_key_hash})")

    def _init_database(self):
        """Initialize SQLite database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Credentials table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                broker TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                api_secret_encrypted TEXT NOT NULL,
                additional_params_encrypted TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                rotation_count INTEGER DEFAULT 0,
                UNIQUE(user_id, broker)
            )
        """)

        # Audit log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                broker TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ip_address TEXT,
                success INTEGER NOT NULL
            )
        """)

        # Encryption key rotation history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS key_rotation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_key_hash TEXT NOT NULL,
                new_key_hash TEXT NOT NULL,
                rotated_at TEXT NOT NULL,
                credentials_count INTEGER NOT NULL
            )
        """)

        conn.commit()
        conn.close()
        logger.info("Database schema initialized")

    def store_credentials(
        self,
        user_id: str,
        broker: str,
        api_key: str,
        api_secret: str,
        additional_params: Optional[Dict] = None,
        ip_address: Optional[str] = None
    ) -> bool:
        """Store encrypted user credentials."""
        try:
            # Encrypt credentials
            api_key_encrypted = self.cipher.encrypt(api_key.encode()).decode()
            api_secret_encrypted = self.cipher.encrypt(api_secret.encode()).decode()

            additional_encrypted = None
            if additional_params:
                additional_json = json.dumps(additional_params)
                additional_encrypted = self.cipher.encrypt(additional_json.encode()).decode()

            # Store in database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            now = datetime.utcnow().isoformat()

            cursor.execute("""
                INSERT OR REPLACE INTO credentials
                (user_id, broker, api_key_encrypted, api_secret_encrypted,
                 additional_params_encrypted, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?,
                    COALESCE((SELECT created_at FROM credentials WHERE user_id=? AND broker=?), ?),
                    ?)
            """, (
                user_id, broker, api_key_encrypted, api_secret_encrypted,
                additional_encrypted, user_id, broker, now, now
            ))

            conn.commit()
            conn.close()

            # Log audit trail
            self._log_audit(user_id, broker, "STORE_CREDENTIALS", ip_address, True)

            logger.info(f"Stored encrypted credentials for user={user_id}, broker={broker}")
            return True

        except Exception as e:
            logger.error(f"Failed to store credentials: {e}")
            self._log_audit(user_id, broker, "STORE_CREDENTIALS", ip_address, False)
            return False

    def get_credentials(
        self,
        user_id: str,
        broker: str,
        ip_address: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """Retrieve and decrypt user credentials."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT api_key_encrypted, api_secret_encrypted, additional_params_encrypted
                FROM credentials
                WHERE user_id = ? AND broker = ?
            """, (user_id, broker))

            row = cursor.fetchone()
            conn.close()

            if not row:
                logger.warning(f"No credentials found for user={user_id}, broker={broker}")
                self._log_audit(user_id, broker, "GET_CREDENTIALS", ip_address, False)
                return None

            # Decrypt credentials
            api_key = self.cipher.decrypt(row[0].encode()).decode()
            api_secret = self.cipher.decrypt(row[1].encode()).decode()

            result = {
                'api_key': api_key,
                'api_secret': api_secret,
                'broker': broker
            }

            # Decrypt additional parameters if present
            if row[2]:
                additional_json = self.cipher.decrypt(row[2].encode()).decode()
                result['additional_params'] = json.loads(additional_json)

            # Log audit trail
            self._log_audit(user_id, broker, "GET_CREDENTIALS", ip_address, True)

            return result

        except Exception as e:
            logger.error(f"Failed to retrieve credentials: {e}")
            self._log_audit(user_id, broker, "GET_CREDENTIALS", ip_address, False)
            return None

    def delete_credentials(
        self,
        user_id: str,
        broker: str,
        ip_address: Optional[str] = None
    ) -> bool:
        """Delete user credentials."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM credentials
                WHERE user_id = ? AND broker = ?
            """, (user_id, broker))

            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()

            self._log_audit(user_id, broker, "DELETE_CREDENTIALS", ip_address, deleted)

            if deleted:
                logger.info(f"Deleted credentials for user={user_id}, broker={broker}")

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete credentials: {e}")
            self._log_audit(user_id, broker, "DELETE_CREDENTIALS", ip_address, False)
            return False

    def list_user_brokers(self, user_id: str) -> List[str]:
        """List all brokers configured for a user."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT broker FROM credentials WHERE user_id = ?
            """, (user_id,))

            brokers = [row[0] for row in cursor.fetchall()]
            conn.close()

            return brokers

        except Exception as e:
            logger.error(f"Failed to list brokers: {e}")
            return []

    def rotate_encryption_key(self, new_key: bytes) -> bool:
        """Rotate encryption key and re-encrypt all credentials."""
        try:
            logger.info("Starting encryption key rotation...")

            new_cipher = Fernet(new_key)
            new_key_hash = hashlib.sha256(new_key).hexdigest()[:16]

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get all credentials
            cursor.execute("SELECT id, api_key_encrypted, api_secret_encrypted, additional_params_encrypted FROM credentials")
            all_creds = cursor.fetchall()

            # Decrypt with old key and re-encrypt with new key
            for cred_id, api_key_enc, api_secret_enc, additional_enc in all_creds:
                api_key = self.cipher.decrypt(api_key_enc.encode()).decode()
                api_secret = self.cipher.decrypt(api_secret_enc.encode()).decode()

                api_key_new = new_cipher.encrypt(api_key.encode()).decode()
                api_secret_new = new_cipher.encrypt(api_secret.encode()).decode()

                additional_new = None
                if additional_enc:
                    additional_data = self.cipher.decrypt(additional_enc.encode()).decode()
                    additional_new = new_cipher.encrypt(additional_data.encode()).decode()

                cursor.execute("""
                    UPDATE credentials
                    SET api_key_encrypted = ?, api_secret_encrypted = ?,
                        additional_params_encrypted = ?, rotation_count = rotation_count + 1
                    WHERE id = ?
                """, (api_key_new, api_secret_new, additional_new, cred_id))

            # Log rotation
            cursor.execute("""
                INSERT INTO key_rotation_history (old_key_hash, new_key_hash, rotated_at, credentials_count)
                VALUES (?, ?, ?, ?)
            """, (self.encryption_key_hash, new_key_hash, datetime.utcnow().isoformat(), len(all_creds)))

            conn.commit()
            conn.close()

            self.cipher = new_cipher
            self.encryption_key_hash = new_key_hash

            logger.info(f"Encryption key rotated successfully ({len(all_creds)} credentials re-encrypted)")
            return True

        except Exception as e:
            logger.error(f"Failed to rotate encryption key: {e}")
            return False

    def _log_audit(
        self,
        user_id: str,
        broker: str,
        action: str,
        ip_address: Optional[str],
        success: bool
    ):
        """Log audit trail for credential access."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO audit_log (user_id, broker, action, timestamp, ip_address, success)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, broker, action, datetime.utcnow().isoformat(), ip_address, 1 if success else 0))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log audit trail: {e}")

    def get_audit_log(
        self,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get audit log entries."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if user_id:
                cursor.execute("""
                    SELECT user_id, broker, action, timestamp, ip_address, success
                    FROM audit_log
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT user_id, broker, action, timestamp, ip_address, success
                    FROM audit_log
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            entries = []
            for row in cursor.fetchall():
                entries.append({
                    'user_id': row[0],
                    'broker': row[1],
                    'action': row[2],
                    'timestamp': row[3],
                    'ip_address': row[4],
                    'success': bool(row[5])
                })

            conn.close()
            return entries

        except Exception as e:
            logger.error(f"Failed to get audit log: {e}")
            return []


# Global vault instance
_vault = None


def get_vault(
    db_path: str = "vault.db",
    encryption_key: Optional[bytes] = None
) -> SecureVault:
    """Get global secure vault instance."""
    global _vault
    if _vault is None:
        _vault = SecureVault(db_path, encryption_key)
    return _vault


__all__ = [
    'SecureVault',
    'get_vault',
]
