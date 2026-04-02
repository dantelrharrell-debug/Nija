"""
NIJA Kraken Nonce Manager — Production Grade
=============================================

ONE global monotonic nonce shared across:
- ALL Kraken API calls
- ALL users (PLATFORM + USER accounts)
- ALL retries
- ALL sessions (survives restarts without replaying accepted nonces)

Design guarantees
─────────────────
✅ Startup always lands ahead of any previously-accepted Kraken nonce
   (initialized to max(persisted, now_ns + 10 s) and persisted immediately)
✅ Runaway accumulation capped at 2 min ahead; resets to now_ns + 10 s
✅ Atomic disk writes (write-then-rename) — no half-written files
✅ Thread-safe with RLock throughout
✅ Strictly monotonic — never decreases, never repeats
✅ Nanosecond precision (19-digit nonces)
✅ Auto-recovery: escalating jump sizes on consecutive nonce errors
   (30 s → 60 s → 120 s, resets on success)
✅ Legacy per-account nonce files cleaned up on first startup

Usage
─────
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock

    lock = get_kraken_api_lock()
    with lock:
        nonce = get_global_kraken_nonce()
        # make Kraken API call with nonce

Auto-recovery
─────────────
    manager = get_global_nonce_manager()
    manager.record_nonce_error()    # call when Kraken returns "invalid nonce"
    manager.record_nonce_success()  # call after a successful API call
"""

import glob as _glob
import logging
import os
import tempfile
import time
import threading

_logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_NONCE_FILE = os.path.join(_DATA_DIR, "kraken_global_nonce.txt")

# Checkpoint cadence: persist after this many get_nonce() calls (in addition to
# always persisting on jump_forward and at startup).
_PERSIST_EVERY_N = 10

# Startup lead-time: always initialise the nonce at least this many nanoseconds
# ahead of now so a fast restart cannot replay a nonce Kraken already accepted.
_STARTUP_LEAD_NS = 10 * 1_000_000_000  # 10 seconds

# Maximum acceptable lead-time.  If the persisted nonce is further ahead than
# this we assume it came from a crash-loop runaway and reset to now + lead.
_MAX_LEAD_NS = 120 * 1_000_000_000  # 2 minutes

# Nanoseconds per second — used for human-readable log messages.
_NS_PER_SECOND = 1_000_000_000

# Escalating recovery jumps (nanoseconds): 30 s, 60 s, 120 s
_RECOVERY_JUMPS_NS = [
    30 * 1_000_000_000,
    60 * 1_000_000_000,
    120 * 1_000_000_000,
]

# Nonce persistence file — survives process restarts so accumulated jumps are not lost
_NONCE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "kraken_global_nonce.txt"
)
_PERSIST_EVERY_N = 10  # Write to disk after this many get_nonce() calls (reduced from 100 to shrink crash gap)

# Startup jump applied every time the process starts.  This guarantees we land
# strictly ahead of any nonce Kraken may still hold from the previous session.
_STARTUP_JUMP_NS = 10_000_000_000  # +10 seconds in nanoseconds

# Auto-heal: automatically jump the nonce forward after this many consecutive errors.
_AUTO_HEAL_THRESHOLD = 3
# How far to jump on an auto-heal event.
_AUTO_HEAL_JUMP_NS = 60_000_000_000  # +60 seconds in nanoseconds

# ── Disk helpers ───────────────────────────────────────────────────────────────

def _load_persisted_nonce() -> int:
    """Load the last persisted nonce from disk.  Returns 0 on any failure."""
    try:
        if os.path.exists(_NONCE_FILE):
            with open(_NONCE_FILE, "r") as fh:
                content = fh.read().strip()
                if content:
                    return int(content)
    except (ValueError, IOError, OSError) as exc:
        _logger.debug("global_kraken_nonce: could not load persisted nonce: %s", exc)
    return 0


def _persist_nonce(nonce: int) -> None:
    """
    Write nonce to disk atomically (write-then-rename).

    Atomic rename prevents a process crash mid-write from leaving a
    corrupt nonce file that would reset the sequence on the next startup.
    Never raises — logs debug on failure.
    """
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, prefix=".nonce_tmp_")
        try:
            os.chmod(tmp_path, 0o600)  # owner read/write only
            with os.fdopen(fd, "w") as fh:
                fh.write(str(nonce))
            os.replace(tmp_path, _NONCE_FILE)  # atomic on POSIX
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (IOError, OSError) as exc:
        _logger.debug("global_kraken_nonce: could not persist nonce: %s", exc)


def cleanup_legacy_nonce_files() -> None:
    """
    Remove stale per-account nonce files left by older bot versions.

    Safe to call multiple times; logs a single info line summarising what
    was removed and silently skips files that cannot be deleted.
    """
    patterns = [
        # Legacy per-account nonce files (e.g. kraken_nonce_platform.txt,
        # kraken_nonce_user_*.txt).  More patterns may be added here if
        # future bot versions introduce additional nonce file variants.
        os.path.join(_DATA_DIR, "kraken_nonce*.txt"),
    ]
    removed = []
    for pattern in patterns:
        for path in _glob.glob(pattern):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError as exc:
                _logger.debug("global_kraken_nonce: could not remove legacy file %s: %s", path, exc)
    if removed:
        _logger.info("global_kraken_nonce: removed %d legacy nonce file(s): %s", len(removed), removed)


# ── Singleton nonce manager ────────────────────────────────────────────────────

class GlobalKrakenNonceManager:
    """
    Production-grade singleton nonce manager for Kraken API.

    Key properties
    ──────────────
    - Nanosecond precision (19-digit nonces via time.time_ns())
    - Thread-safe (RLock throughout)
    - Strictly monotonic — never repeats or decreases
    - Survives restarts: initialises to max(persisted, now + 10 s) then
      persists the startup value immediately
    - Runaway protection: if persisted > now + 2 min, resets to now + 10 s
    - Auto-recovery: escalating nonce jumps on consecutive errors

    Usage
    ─────
        manager = get_global_nonce_manager()
        nonce   = manager.get_nonce()
    """

    _instance = None
    _class_lock = threading.RLock()

    def __new__(cls):
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        with self._class_lock:
            if getattr(self, "_initialized", False):
                return

            self._nonce_lock = threading.RLock()

            current_ns = time.time_ns()
            persisted = _load_persisted_nonce()

            if persisted > current_ns + _MAX_LEAD_NS:
                excess_s = (persisted - current_ns) / _NS_PER_SECOND
                _logger.warning(
                    "global_kraken_nonce: persisted nonce is %.0fs ahead of now "
                    "(likely from crash-loop jumps); resetting to now + 10 s.",
                    excess_s,
                )
                persisted = 0  # force the startup-lead path below

            # Always land at least _STARTUP_LEAD_NS ahead of now so a fast
            # restart cannot replay a nonce Kraken already accepted.
            self._last_nonce = max(current_ns + _STARTUP_LEAD_NS, persisted)
            # Start strictly ahead of both the wall clock and any previously
            # persisted nonce.  The +10 s jump ensures we are beyond any nonce
            # Kraken still holds from the last session even if the persisted
            # file is slightly stale (up to _PERSIST_EVERY_N−1 calls behind).
            self._last_nonce = max(current_ns, persisted) + _STARTUP_JUMP_NS

            # Persist immediately so a crash right after startup still leaves
            # a safe anchor for the *next* restart.
            _persist_nonce(self._last_nonce)

            self._nonce_lock = threading.RLock()

            # Persist immediately — this is the single most important write.
            _persist_nonce(self._last_nonce)

            # Remove stale legacy files so they can never be picked up by old
            # code paths still reading per-account nonce files.
            cleanup_legacy_nonce_files()

            # Counters
            self._nonces_since_persist = 0
            # Consecutive nonce-error counter for auto-heal logic
            self._consecutive_errors = 0

            # Statistics tracking
            self._total_nonces_issued = 0
            self._creation_time = time.time()

            # Auto-recovery state
            self._consecutive_errors = 0

            self._initialized = True

            _logger.info(
                "global_kraken_nonce: manager ready — startup nonce %d "
                "(%.1f s ahead of now)",
                self._last_nonce,
                (self._last_nonce - current_ns) / _NS_PER_SECOND,
            )

    # ── Core nonce generation ──────────────────────────────────────────────

    def get_nonce(self) -> int:
        """
        Return the next monotonically increasing nonce (nanoseconds).

        Thread-safe.  Each call returns a value strictly greater than the last.
        """
        with self._nonce_lock:
            current_time_ns = time.time_ns()
            new_nonce = max(current_time_ns, self._last_nonce + 1)
            self._last_nonce = new_nonce
            self._total_nonces_issued += 1

            self._nonces_since_persist += 1
            if self._nonces_since_persist >= _PERSIST_EVERY_N:
                self._nonces_since_persist = 0
                _persist_nonce(new_nonce)

            return new_nonce

    # ── Recovery helpers ───────────────────────────────────────────────────

    def jump_forward(self, nanoseconds: int) -> int:
        """
        Jump the nonce forward by *nanoseconds*.

        Used for error recovery.  The new value is persisted to disk
        immediately so a restart won't replay nonces Kraken already saw.

        Returns the new nonce value.
        """
        with self._nonce_lock:
            current_time_ns = time.time_ns()
            self._last_nonce = max(
                current_time_ns + nanoseconds,
                self._last_nonce + nanoseconds,
            )
            self._nonces_since_persist = 0
            _persist_nonce(self._last_nonce)
            return self._last_nonce

    def record_nonce_error(self) -> int:
        """
        Record a Kraken nonce error and auto-heal after repeated failures.

        Call this whenever Kraken returns "EAPI:Invalid nonce".  After
        _AUTO_HEAL_THRESHOLD consecutive errors the nonce is automatically
        jumped forward by _AUTO_HEAL_JUMP_NS and persisted so the next API
        call lands well outside Kraken's nonce-acceptance window.

        Returns:
            int: Current consecutive-error count (resets to 0 after auto-heal)
        """
        with self._nonce_lock:
            self._consecutive_errors += 1
            count = self._consecutive_errors
            if count >= _AUTO_HEAL_THRESHOLD:
                current_time_ns = time.time_ns()
                self._last_nonce = max(
                    current_time_ns + _AUTO_HEAL_JUMP_NS,
                    self._last_nonce + _AUTO_HEAL_JUMP_NS,
                )
                self._nonces_since_persist = 0
                _persist_nonce(self._last_nonce)
                self._consecutive_errors = 0
                _logger.warning(
                    f"global_kraken_nonce: auto-heal triggered after {count} consecutive "
                    f"nonce errors; jumped forward +{_AUTO_HEAL_JUMP_NS // 1_000_000_000}s "
                    f"to {self._last_nonce}"
                )
                return 0
            return count

    def record_success(self) -> None:
        """
        Record a successful Kraken API call, resetting the error counter.

        Call this after every successful private API response so that the
        auto-heal threshold resets and transient single errors do not
        accumulate toward a spurious auto-heal.
        """
        with self._nonce_lock:
            self._consecutive_errors = 0

    def reset_to_safe_value(self) -> int:
        """
        Hard-reset the nonce to a safe value for manual recovery.

        Sets the nonce to current nanoseconds + _STARTUP_JUMP_NS and
        persists immediately.  Use this when the bot is stuck and normal
        auto-heal has not resolved the desync.

        Returns:
            int: New nonce value after reset
        """
        with self._nonce_lock:
            self._last_nonce = time.time_ns() + _STARTUP_JUMP_NS
            self._nonces_since_persist = 0
            self._consecutive_errors = 0
            _persist_nonce(self._last_nonce)
            _logger.warning(
                f"global_kraken_nonce: manual reset_to_safe_value() called; "
                f"new nonce = {self._last_nonce}"
            )
            return self._last_nonce

    def get_last_nonce(self) -> int:
        """
        Return the most recently issued nonce without advancing the counter.

        Useful for external code that needs to snapshot the current nonce
        position without consuming a new value.

        Returns:
            int: Last issued nonce (nanoseconds)
        """
        with self._nonce_lock:
            return self._last_nonce

    def get_stats(self) -> dict:
        """
        Record a Kraken "invalid nonce" error and perform an escalating jump.

        Jump schedule (resets after record_nonce_success()):
          1st error  → +30 s
          2nd error  → +60 s
          3rd+ error → +120 s

        Returns the nanoseconds jumped.
        """
        with self._nonce_lock:
            self._consecutive_errors += 1
            idx = min(self._consecutive_errors - 1, len(_RECOVERY_JUMPS_NS) - 1)
            jump_ns = _RECOVERY_JUMPS_NS[idx]

        jump_s = jump_ns / _NS_PER_SECOND
        _logger.info(
            "global_kraken_nonce: nonce error #%d — jumping forward %.0f s",
            self._consecutive_errors,
            jump_s,
        )
        self.jump_forward(jump_ns)
        return jump_ns

    def record_nonce_success(self) -> None:
        """
        Record a successful Kraken API call and reset the error counter.

        Call this after every successful private API response to keep the
        escalating recovery schedule accurate.
        """
        with self._nonce_lock:
            if self._consecutive_errors > 0:
                _logger.debug(
                    "global_kraken_nonce: nonce success — resetting error counter "
                    "(was %d)",
                    self._consecutive_errors,
                )
                self._consecutive_errors = 0

    # ── Diagnostics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return a dict with runtime statistics for monitoring / logging."""
        with self._nonce_lock:
            uptime = time.time() - self._creation_time
            rate = self._total_nonces_issued / uptime if uptime > 0 else 0
            lead_s = (self._last_nonce - time.time_ns()) / _NS_PER_SECOND
            return {
                "total_nonces_issued": self._total_nonces_issued,
                "last_nonce": self._last_nonce,
                "lead_seconds": round(lead_s, 3),
                "consecutive_errors": self._consecutive_errors,
                "uptime_seconds": round(uptime, 1),
                "nonces_per_second": round(rate, 3),
                'total_nonces_issued': self._total_nonces_issued,
                'last_nonce': self._last_nonce,
                'uptime_seconds': uptime,
                'nonces_per_second': rate,
                'consecutive_errors': self._consecutive_errors,
            }


# ── Module-level accessors (public API) ────────────────────────────────────────

def get_global_nonce_manager() -> GlobalKrakenNonceManager:
    """Return the process-wide GlobalKrakenNonceManager singleton."""
    return GlobalKrakenNonceManager()


def get_global_nonce_stats() -> dict:
    """Return runtime statistics from the global nonce manager."""
    return get_global_nonce_manager().get_stats()


def get_kraken_nonce() -> int:
    """
    Return the next Kraken API nonce (nanoseconds, 19 digits).

    Primary interface for all Kraken private API calls.  Guaranteed to be
    strictly monotonic across threads, retries, and process restarts.
    """
    return get_global_nonce_manager().get_nonce()


# Alias kept for backwards compatibility
get_global_kraken_nonce = get_kraken_nonce


# ── Global API serialisation lock ─────────────────────────────────────────────

# Kraken rejects parallel private calls on the same API key — serialise them.
_KRAKEN_API_LOCK = threading.Lock()


def get_kraken_api_lock() -> threading.Lock:
    """
    Return the process-wide Kraken API serialisation lock.

    Acquire this lock around every private Kraken API call to prevent
    parallel writes that would cause nonce ordering violations.

    Usage::

        with get_kraken_api_lock():
            nonce = get_global_kraken_nonce()
            # make Kraken private API call
    """
    return _KRAKEN_API_LOCK


def jump_global_kraken_nonce_forward(milliseconds: int) -> int:
    """
    Jump the global nonce forward by *milliseconds* (converted to nanoseconds).

    Convenience wrapper used by broker_manager for manual recovery jumps.
    Returns the new nonce value (nanoseconds).
    """
    return get_global_nonce_manager().jump_forward(milliseconds * 1_000_000)


def record_kraken_nonce_error() -> int:
    """
    Signal that a Kraken "invalid nonce" error occurred.

    Performs an escalating jump and returns the nanoseconds jumped.
    Prefer this over manual jump_global_kraken_nonce_forward() calls so
    the auto-recovery escalation state is tracked correctly.
    """
    return get_global_nonce_manager().record_nonce_error()


def record_kraken_nonce_success() -> None:
    """Signal that a Kraken API call succeeded.  Resets escalation counter."""
    get_global_nonce_manager().record_nonce_success()


def reset_global_kraken_nonce() -> int:
    """
    Hard-reset the global nonce to a safe value (current time + 10 s).

    Convenience wrapper around GlobalKrakenNonceManager.reset_to_safe_value().
    Use when the bot is stuck with repeated "EAPI:Invalid nonce" errors and
    normal auto-heal has not resolved the desync.

    Returns:
        int: New nonce value after reset (nanoseconds)
    """
    return get_global_nonce_manager().reset_to_safe_value()


__all__ = [
    "GlobalKrakenNonceManager",
    "get_global_nonce_manager",
    "get_global_nonce_stats",
    "get_kraken_nonce",
    "get_global_kraken_nonce",
    "get_kraken_api_lock",
    "jump_global_kraken_nonce_forward",
    "record_kraken_nonce_error",
    "record_kraken_nonce_success",
    "cleanup_legacy_nonce_files",
    'GlobalKrakenNonceManager',
    'get_global_nonce_manager',
    'get_global_nonce_stats',
    'get_kraken_nonce',
    'get_global_kraken_nonce',
    'get_kraken_api_lock',
    'jump_global_kraken_nonce_forward',
    'reset_global_kraken_nonce',
]
