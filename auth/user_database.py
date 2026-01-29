"""
NIJA User Database - Persistent User Management

Provides database-backed user storage with proper password hashing.
"""

import logging
import sqlite3
import hashlib
import secrets
from typing import Dict, Optional, List
from datetime import datetime
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

logger = logging.getLogger("nija.auth.userdb")

# Use Argon2 for password hashing (OWASP recommended)
ph = PasswordHasher()


class UserDatabase:
    """
    Database-backed user management with secure password storage.
    """

    def __init__(self, db_path: str = "users.db"):
        """
        Initialize user database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_database()
        logger.info(f"User database initialized (db={db_path})")

    def _init_database(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                subscription_tier TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login TEXT,
                enabled INTEGER DEFAULT 1,
                email_verified INTEGER DEFAULT 0
            )
        """)

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Login history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ip_address TEXT,
                success INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        conn.commit()
        conn.close()
        logger.info("User database schema initialized")

    def create_user(
        self,
        user_id: str,
        email: str,
        password: str,
        subscription_tier: str = 'basic'
    ) -> bool:
        """
        Create a new user account.

        Args:
            user_id: Unique user identifier
            email: User email address
            password: Plain text password (will be hashed)
            subscription_tier: Subscription level

        Returns:
            bool: True if created successfully
        """
        try:
            # Hash password using Argon2
            password_hash = ph.hash(password)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            now = datetime.utcnow().isoformat()

            cursor.execute("""
                INSERT INTO users (user_id, email, password_hash, subscription_tier, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, email, password_hash, subscription_tier, now, now))

            conn.commit()
            conn.close()

            logger.info(f"Created user: {user_id} ({email})")
            return True

        except sqlite3.IntegrityError as e:
            logger.error(f"User creation failed (duplicate): {e}")
            return False
        except Exception as e:
            logger.error(f"User creation failed: {e}")
            return False

    def verify_password(self, user_id: str, password: str, ip_address: Optional[str] = None) -> bool:
        """
        Verify user password.

        Args:
            user_id: User identifier
            password: Plain text password to verify
            ip_address: IP address for logging

        Returns:
            bool: True if password is correct
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT password_hash, enabled FROM users WHERE user_id = ?
            """, (user_id,))

            row = cursor.fetchone()

            if not row:
                self._log_login(user_id, ip_address, False)
                conn.close()
                return False

            password_hash, enabled = row

            if not enabled:
                logger.warning(f"Login attempt for disabled user: {user_id}")
                self._log_login(user_id, ip_address, False)
                conn.close()
                return False

            # Verify password with Argon2
            try:
                ph.verify(password_hash, password)

                # Update last login time
                cursor.execute("""
                    UPDATE users SET last_login = ? WHERE user_id = ?
                """, (datetime.utcnow().isoformat(), user_id))

                conn.commit()
                conn.close()

                self._log_login(user_id, ip_address, True)
                return True

            except VerifyMismatchError:
                self._log_login(user_id, ip_address, False)
                conn.close()
                return False

        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False

    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user profile."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT user_id, email, subscription_tier, created_at, last_login, enabled, email_verified
                FROM users
                WHERE user_id = ?
            """, (user_id,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return {
                'user_id': row[0],
                'email': row[1],
                'subscription_tier': row[2],
                'created_at': row[3],
                'last_login': row[4],
                'enabled': bool(row[5]),
                'email_verified': bool(row[6])
            }

        except Exception as e:
            logger.error(f"Failed to get user: {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email address."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT user_id, email, subscription_tier, created_at, last_login, enabled, email_verified
                FROM users
                WHERE email = ?
            """, (email,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return {
                'user_id': row[0],
                'email': row[1],
                'subscription_tier': row[2],
                'created_at': row[3],
                'last_login': row[4],
                'enabled': bool(row[5]),
                'email_verified': bool(row[6])
            }

        except Exception as e:
            logger.error(f"Failed to get user by email: {e}")
            return None

    def update_user(self, user_id: str, updates: Dict) -> bool:
        """Update user profile."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Build update query dynamically
            allowed_fields = ['email', 'subscription_tier', 'enabled', 'email_verified']
            update_fields = []
            update_values = []

            for field in allowed_fields:
                if field in updates:
                    update_fields.append(f"{field} = ?")
                    update_values.append(updates[field])

            if not update_fields:
                return False

            # Add updated_at timestamp
            update_fields.append("updated_at = ?")
            update_values.append(datetime.utcnow().isoformat())
            update_values.append(user_id)

            query = f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = ?"
            cursor.execute(query, update_values)

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()

            if updated:
                logger.info(f"Updated user {user_id}: {updates}")

            return updated

        except Exception as e:
            logger.error(f"Failed to update user: {e}")
            return False

    def change_password(self, user_id: str, new_password: str) -> bool:
        """Change user password."""
        try:
            password_hash = ph.hash(new_password)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?
            """, (password_hash, datetime.utcnow().isoformat(), user_id))

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()

            if updated:
                logger.info(f"Password changed for user {user_id}")

            return updated

        except Exception as e:
            logger.error(f"Failed to change password: {e}")
            return False

    def _log_login(self, user_id: str, ip_address: Optional[str], success: bool):
        """Log login attempt."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO login_history (user_id, timestamp, ip_address, success)
                VALUES (?, ?, ?, ?)
            """, (user_id, datetime.utcnow().isoformat(), ip_address, 1 if success else 0))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log login: {e}")

    def create_session(
        self,
        user_id: str,
        expires_at: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """Create a new session."""
        try:
            session_id = secrets.token_urlsafe(32)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO sessions (session_id, user_id, created_at, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, user_id, datetime.utcnow().isoformat(), expires_at, ip_address, user_agent))

            conn.commit()
            conn.close()

            return session_id

        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return None


# Global instance
_user_db = None


def get_user_database(db_path: str = "users.db") -> UserDatabase:
    """Get global user database instance."""
    global _user_db
    if _user_db is None:
        _user_db = UserDatabase(db_path)
    return _user_db


__all__ = [
    'UserDatabase',
    'get_user_database',
]
