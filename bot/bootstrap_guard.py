"""
Bootstrap Guard — Prevent duplicate bot instances from running simultaneously.

Uses file-based locking to ensure only one bot process runs at a time.
If a second instance attempts to acquire the guard, it hard stops with clear messaging.
"""

import logging
import os
import sys
import fcntl
import signal
import atexit
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.bootstrap_guard")

# Global lock file handle — held for the lifetime of the process
_GUARD_LOCK_HANDLE: Optional[object] = None
_GUARD_LOCK_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    ".bootstrap.lock",
)


def _ensure_lock_dir() -> None:
    """Ensure lock directory exists."""
    lock_dir = os.path.dirname(_GUARD_LOCK_PATH)
    os.makedirs(lock_dir, exist_ok=True)


def _cleanup_guard() -> None:
    """Release guard on process exit."""
    global _GUARD_LOCK_HANDLE
    if _GUARD_LOCK_HANDLE is not None:
        try:
            fcntl.flock(_GUARD_LOCK_HANDLE, fcntl.LOCK_UN)
            _GUARD_LOCK_HANDLE.close()
            _GUARD_LOCK_HANDLE = None
            logger.info("🔓 Bootstrap guard released")
        except Exception as exc:
            logger.debug("Bootstrap guard cleanup failed: %s", exc)


def acquire_bootstrap_guard() -> None:
    """Acquire an exclusive bootstrap guard.

    This function enforces that only ONE NIJA bot instance can run at a time.

    If the guard is already held by another process, this function logs a
    critical error and calls sys.exit(1) with a clear message.

    On first call (successful acquisition), the guard is held for the lifetime
    of the process and automatically released on exit via atexit handler.

    Raises:
        SystemExit(1): If the guard is already held by another process.
    """
    global _GUARD_LOCK_HANDLE

    if _GUARD_LOCK_HANDLE is not None:
        logger.warning("⚠️ Bootstrap guard already acquired by this process (idempotent, no-op)")
        return

    _ensure_lock_dir()

    # Open or create the lock file
    try:
        lock_file = open(_GUARD_LOCK_PATH, "w")
    except IOError as exc:
        logger.critical("❌ BOOTSTRAP GUARD FATAL ERROR")
        logger.critical("   Cannot open lock file: %s", _GUARD_LOCK_PATH)
        logger.critical("   Error: %s", exc)
        sys.exit(1)

    # Attempt exclusive lock (non-blocking)
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.critical("")
        logger.critical("=" * 80)
        logger.critical("🚫 BOOTSTRAP GUARD: DUPLICATE BOT DETECTED")
        logger.critical("=" * 80)
        logger.critical("")
        logger.critical("   ❌ Another NIJA bot instance is already running.")
        logger.critical("")
        logger.critical("   To start a new instance:")
        logger.critical("     1. Kill the existing bot process")
        logger.critical("     2. Remove the lock file: %s", _GUARD_LOCK_PATH)
        logger.critical("     3. Restart the bot")
        logger.critical("")
        logger.critical("=" * 80)
        logger.critical("")
        lock_file.close()
        sys.exit(1)

    # Lock acquired — write PID and timestamp
    _GUARD_LOCK_HANDLE = lock_file
    try:
        lock_file.write(f"PID={os.getpid()}\n")
        lock_file.flush()
    except Exception as exc:
        logger.warning("⚠️ Bootstrap guard PID write failed: %s", exc)

    # Register cleanup handler
    atexit.register(_cleanup_guard)

    logger.info("=" * 80)
    logger.info("✅ BOOTSTRAP GUARD ACQUIRED")
    logger.info("=" * 80)
    logger.info("   PID: %s", os.getpid())
    logger.info("   Lock: %s", _GUARD_LOCK_PATH)
    logger.info("   Only instance: YES")
    logger.info("=" * 80)


def release_bootstrap_guard() -> None:
    """Manually release the bootstrap guard (normally automatic on exit)."""
    _cleanup_guard()


def is_guard_held() -> bool:
    """Check if bootstrap guard is currently held by this process.

    Returns:
        True if guard is held, False otherwise.
    """
    return _GUARD_LOCK_HANDLE is not None
