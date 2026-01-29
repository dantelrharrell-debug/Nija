"""
NIJA User Nonce Manager
=======================

Per-user nonce tracking and self-healing for Kraken API.

Features:
- Individual nonce files per user
- Automatic nonce collision detection
- Self-healing nonce recovery
- Thread-safe operations
"""

import os
import time
import logging
import threading
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger('nija.nonce')

# Data directory for nonce files
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class UserNonceManager:
    """
    Manages nonces for individual users with automatic self-healing.

    Each user gets their own nonce file and tracking to prevent collisions.
    Automatically detects and recovers from nonce errors.
    """

    def __init__(self):
        """Initialize the user nonce manager."""
        # Per-user locks for thread-safety
        self._user_locks: Dict[str, threading.Lock] = {}

        # Per-user last nonce tracking
        self._user_nonces: Dict[str, int] = {}

        # Per-user error tracking for auto-healing
        self._user_nonce_errors: Dict[str, int] = {}

        # Per-user last successful nonce (for debugging)
        self._user_last_success: Dict[str, int] = {}

        # Global lock for manager initialization
        self._manager_lock = threading.Lock()

        # Ensure data directory exists
        os.makedirs(_data_dir, exist_ok=True)

        logger.info("UserNonceManager initialized")

    def _get_nonce_file(self, user_id: str) -> str:
        """
        Get the nonce file path for a specific user.

        Args:
            user_id: User identifier

        Returns:
            str: Path to user's nonce file
        """
        # Sanitize user_id for filesystem
        safe_user_id = user_id.replace('/', '_').replace('\\', '_')
        return os.path.join(_data_dir, f"kraken_nonce_{safe_user_id}.txt")

    def _get_user_lock(self, user_id: str) -> threading.Lock:
        """
        Get or create a lock for a specific user.

        Args:
            user_id: User identifier

        Returns:
            threading.Lock: User's lock
        """
        with self._manager_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.Lock()
            return self._user_locks[user_id]

    def _load_nonce(self, user_id: str) -> int:
        """
        Load last nonce from user's file.

        Args:
            user_id: User identifier

        Returns:
            int: Last nonce (0 if file doesn't exist)
        """
        nonce_file = self._get_nonce_file(user_id)

        if not os.path.exists(nonce_file):
            return 0

        try:
            with open(nonce_file, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
        except (ValueError, IOError) as e:
            logger.debug(f"Could not read nonce file for {user_id}: {e}")

        return 0

    def _save_nonce(self, user_id: str, nonce: int):
        """
        Save nonce to user's file.

        Args:
            user_id: User identifier
            nonce: Nonce to save
        """
        nonce_file = self._get_nonce_file(user_id)

        try:
            # Write to temp file first, then rename for atomicity
            temp_file = nonce_file + '.tmp'
            with open(temp_file, 'w') as f:
                f.write(str(nonce))
            os.replace(temp_file, nonce_file)
        except IOError as e:
            logger.debug(f"Could not save nonce for {user_id}: {e}")

    def get_nonce(self, user_id: str) -> int:
        """
        Get next nonce for user with automatic self-healing.

        Args:
            user_id: User identifier

        Returns:
            int: Next nonce to use
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Load last persisted nonce
            last_nonce = self._load_nonce(user_id)

            # Get current time-based nonce
            now_us = int(time.time() * 1000000)

            # Ensure nonce is monotonically increasing
            # Use max of: current time, last persisted nonce + 1
            nonce = max(now_us, last_nonce + 1)

            # Track in memory
            self._user_nonces[user_id] = nonce

            # Persist to file
            self._save_nonce(user_id, nonce)

            return nonce

    def record_nonce_error(self, user_id: str) -> bool:
        """
        Record a nonce error and determine if self-healing is needed.

        Args:
            user_id: User identifier

        Returns:
            bool: True if self-healing was triggered
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Increment error count
            if user_id not in self._user_nonce_errors:
                self._user_nonce_errors[user_id] = 0

            self._user_nonce_errors[user_id] += 1
            error_count = self._user_nonce_errors[user_id]

            logger.warning(f"🔁 Nonce error for {user_id} (count: {error_count})")

            # Trigger self-healing after 2+ errors
            if error_count >= 2:
                return self._heal_nonce(user_id)

            return False

    def _heal_nonce(self, user_id: str) -> bool:
        """
        Self-healing: Jump nonce forward to clear error window.

        Args:
            user_id: User identifier

        Returns:
            bool: True if healing was successful
        """
        try:
            # Get current nonce
            current_nonce = self._user_nonces.get(user_id, 0)

            # Jump forward by 60 seconds
            jump_amount = 60 * 1000000  # 60 seconds in microseconds

            # Calculate new nonce (max of time + jump, current + jump)
            now_us = int(time.time() * 1000000)
            healed_nonce = max(now_us + jump_amount, current_nonce + jump_amount)

            # Update and persist
            self._user_nonces[user_id] = healed_nonce
            self._save_nonce(user_id, healed_nonce)

            logger.info(f"✅ Self-healed nonce for {user_id}: jumped +60s to {healed_nonce}")

            # Reset error count after successful healing
            self._user_nonce_errors[user_id] = 0

            return True
        except Exception as e:
            logger.error(f"Failed to heal nonce for {user_id}: {e}")
            return False

    def record_success(self, user_id: str, nonce: int):
        """
        Record a successful API call (resets error count).

        Args:
            user_id: User identifier
            nonce: Nonce that was successful
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Reset error count on success
            self._user_nonce_errors[user_id] = 0

            # Track last successful nonce
            self._user_last_success[user_id] = nonce

    def get_stats(self, user_id: str) -> Dict:
        """
        Get nonce statistics for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: Statistics including last nonce, error count, etc.
        """
        lock = self._get_user_lock(user_id)

        with lock:
            return {
                'user_id': user_id,
                'last_nonce': self._user_nonces.get(user_id, 0),
                'error_count': self._user_nonce_errors.get(user_id, 0),
                'last_success': self._user_last_success.get(user_id, 0),
                'nonce_file': self._get_nonce_file(user_id),
                'has_errors': self._user_nonce_errors.get(user_id, 0) > 0
            }

    def reset_user(self, user_id: str):
        """
        Reset nonce tracking for a user (manual intervention).

        Args:
            user_id: User identifier
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Clear in-memory tracking
            self._user_nonces.pop(user_id, None)
            self._user_nonce_errors.pop(user_id, None)
            self._user_last_success.pop(user_id, None)

            # Delete nonce file
            nonce_file = self._get_nonce_file(user_id)
            if os.path.exists(nonce_file):
                os.remove(nonce_file)

            logger.info(f"Reset nonce tracking for {user_id}")


# Global singleton instance
_user_nonce_manager: Optional[UserNonceManager] = None
_init_lock = threading.Lock()


def get_user_nonce_manager() -> UserNonceManager:
    """
    Get the global user nonce manager instance (singleton).

    Returns:
        UserNonceManager: Global instance
    """
    global _user_nonce_manager

    with _init_lock:
        if _user_nonce_manager is None:
            _user_nonce_manager = UserNonceManager()
        return _user_nonce_manager


__all__ = [
    'UserNonceManager',
    'get_user_nonce_manager',
]
