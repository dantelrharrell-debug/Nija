"""
NIJA User Nonce Manager
=======================

Per-user nonce tracking and self-healing for Kraken API.

Features:
- Individual nonce files per user (completely isolated from PLATFORM nonce)
- Automatic nonce collision detection
- Self-healing nonce recovery
- Thread-safe operations
- NIJA_FORCE_NONCE_RESYNC=1 support: wipes all user nonce files on startup

Design: USER API keys each have their own nonce window at Kraken.  This manager
keeps per-user state files (data/kraken_nonce_<user_id>.state) that are entirely
independent of the PLATFORM KrakenNonceManager singleton.  USER nonce errors
therefore never trigger PLATFORM nuclear resets, and vice-versa.
"""

import os
import stat
import time
import logging
import threading
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger('nija.nonce')

# Data directory for nonce files
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Startup jump for user nonce files: start 10 s ahead of wall-clock on fresh
# file or hot restart so the first call lands safely above Kraken's recorded
# high-water mark for that API key.
_USER_STARTUP_JUMP_MS: int = int(os.environ.get("NIJA_USER_NONCE_STARTUP_JUMP_MS", "10000"))

# Jump amount used when self-healing after consecutive nonce errors (60 s).
_USER_HEAL_JUMP_MS: int = int(os.environ.get("NIJA_USER_NONCE_HEAL_JUMP_MS", "60000"))


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

        # NIJA_FORCE_NONCE_RESYNC=1 — wipe all per-user state files at startup so
        # that USER brokers begin fresh (same semantics as the PLATFORM resync flag).
        if os.environ.get("NIJA_FORCE_NONCE_RESYNC", "").strip() == "1":
            self._wipe_all_nonce_files()
            logger.info("UserNonceManager: NIJA_FORCE_NONCE_RESYNC=1 — all user nonce files wiped")

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
        return os.path.join(_data_dir, f"kraken_nonce_{safe_user_id}.state")

    def _wipe_all_nonce_files(self) -> None:
        """Remove all per-user nonce state files (used by NIJA_FORCE_NONCE_RESYNC=1)."""
        try:
            import glob
            pattern = os.path.join(_data_dir, "kraken_nonce_*.state")
            for path in glob.glob(pattern):
                # Skip the PLATFORM state file (basename is exactly 'kraken_nonce.state')
                if os.path.basename(path) == 'kraken_nonce.state':
                    continue
                try:
                    os.remove(path)
                    logger.debug("UserNonceManager: removed %s", path)
                except OSError as exc:
                    logger.warning("UserNonceManager: could not remove %s: %s", path, exc)
        except Exception as exc:
            logger.warning("UserNonceManager: error during file wipe: %s", exc)

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
        Load last nonce from user's file.  Returns a millisecond-epoch value.

        Handles migration from old nanosecond/microsecond state files:
          - Nanosecond values (>= 10^18): divide by 10^6 to get milliseconds
          - Microsecond values (10^15 – 10^18): divide by 10^3 to get milliseconds
          - Millisecond values (< 10^15): return as-is

        Args:
            user_id: User identifier

        Returns:
            int: Last persisted nonce in milliseconds (0 if file doesn't exist)
        """
        nonce_file = self._get_nonce_file(user_id)

        if not os.path.exists(nonce_file):
            return 0

        try:
            with open(nonce_file, 'r') as f:
                content = f.read().strip()
                if content:
                    value = int(content)
                    # Migrate legacy nanosecond / microsecond values to milliseconds.
                    # Nanoseconds:  value >= 10^18  → divide by 10^6
                    # Microseconds: 10^15 <= value < 10^18 → divide by 10^3
                    # Milliseconds: value < 10^15  → no conversion needed
                    _NS_THRESHOLD = 10 ** 18
                    _US_THRESHOLD = 10 ** 15
                    if value >= _NS_THRESHOLD:
                        value = value // 1_000_000
                    elif value >= _US_THRESHOLD:
                        value = value // 1_000
                    return value
        except (ValueError, IOError) as e:
            logger.debug(f"Could not read nonce file for {user_id}: {e}")

        return 0

    def _save_nonce(self, user_id: str, nonce: int):
        """
        Save nonce to user's file atomically.

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
            # Restrict permissions to owner-only (API credentials context)
            try:
                os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temp_file, nonce_file)
        except IOError as e:
            logger.debug(f"Could not save nonce for {user_id}: {e}")

    def get_nonce(self, user_id: str) -> int:
        """
        Get next nonce for user with automatic self-healing.

        Each user has a completely independent nonce sequence persisted to their
        own state file (data/kraken_nonce_<user_id>.state).  The sequence is
        never shared with the PLATFORM KrakenNonceManager singleton so that
        PLATFORM nuclear resets never affect USER accounts and vice-versa.

        Args:
            user_id: User identifier

        Returns:
            int: Next nonce to use (milliseconds, strictly monotonic)
        """
        lock = self._get_user_lock(user_id)

        with lock:
            last_nonce = self._user_nonces.get(user_id)
            if last_nonce is None:
                # First call this session — load from file
                persisted = self._load_nonce(user_id)
                now_ms = int(time.time() * 1000)
                # Startup jump: ensure we land above the persisted floor
                nonce = max(persisted + 1, now_ms + _USER_STARTUP_JUMP_MS)
            else:
                now_ms = int(time.time() * 1000)
                # Strict monotonic: always greater than the last issued value
                nonce = max(last_nonce + 1, now_ms)

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

        Jumps the per-user nonce forward by _USER_HEAL_JUMP_MS (60 s by default)
        using only local state.  Never touches the PLATFORM KrakenNonceManager
        singleton so PLATFORM nonce health is unaffected.

        Args:
            user_id: User identifier

        Returns:
            bool: True if healing was successful
        """
        try:
            current_nonce = self._user_nonces.get(user_id, 0)
            now_ms = int(time.time() * 1000)
            healed_nonce = max(now_ms + _USER_HEAL_JUMP_MS, current_nonce + _USER_HEAL_JUMP_MS)

            self._user_nonces[user_id] = healed_nonce
            self._save_nonce(user_id, healed_nonce)

            logger.info(f"✅ Self-healed nonce for {user_id}: jumped +{_USER_HEAL_JUMP_MS // 1000}s to {healed_nonce}")
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

    def get_last_nonce(self, user_id: str = "") -> int:
        """
        Return the most recently issued nonce for *user_id* (peek, no increment).

        Args:
            user_id: User identifier

        Returns:
            int: Last issued nonce (0 if none issued yet)
        """
        return self._user_nonces.get(user_id, 0)

    def begin_request(self) -> None:
        """No-op: compatibility stub matching KrakenNonceManager interface."""

    def end_request(self) -> None:
        """No-op: compatibility stub matching KrakenNonceManager interface."""

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
    'force_resync_all_user_nonces',
]


def force_resync_all_user_nonces() -> None:
    """
    Wipe all per-user nonce state files so every USER broker starts fresh on
    next connect().  Equivalent to setting NIJA_FORCE_NONCE_RESYNC=1 at
    startup but callable at runtime (e.g. from the admin dashboard).
    """
    mgr = get_user_nonce_manager()
    mgr._wipe_all_nonce_files()
    # Clear in-memory state as well
    with mgr._manager_lock:
        mgr._user_nonces.clear()
        mgr._user_nonce_errors.clear()
        mgr._user_last_success.clear()
    logger.info("force_resync_all_user_nonces: all user nonce state cleared")
