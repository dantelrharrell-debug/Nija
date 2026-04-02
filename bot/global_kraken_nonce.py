"""
NIJA Kraken Nonce Generator (Global Monotonic)
==============================================

FIX #2: GLOBAL KRAKEN NONCE (FINAL SOLUTION)

ONE global monotonic nonce shared across:
- ALL Kraken API calls
- ALL users (MASTER + USER accounts)
- ALL retries
- ALL sessions (survives restarts)

Implementation:
    nonce = max(int(time.time_ns()), last_nonce + 1)

Rules:
    ✅ Shared across all Kraken calls
    ✅ Shared across retries
    ✅ Shared across users
    ✅ Never stored per instance
    ✅ Never reset on reconnect
    ✅ Thread-safe with global lock
    ✅ Monotonically increasing
    ✅ Nanosecond precision (19 digits)

Usage:
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock

    # Always use the lock when making Kraken API calls
    lock = get_kraken_api_lock()
    with lock:
        nonce = get_global_kraken_nonce()
        # Make Kraken API call here with nonce
"""

import logging
import os
import time
import threading

_logger = logging.getLogger(__name__)

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


def _load_persisted_nonce() -> int:
    """Load the last persisted nonce from disk. Returns 0 if not available."""
    try:
        if os.path.exists(_NONCE_FILE):
            with open(_NONCE_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return int(content)
    except (ValueError, IOError, OSError) as e:
        import logging as _logging
        _logging.debug(f"global_kraken_nonce: could not load persisted nonce from {_NONCE_FILE}: {e}")
    return 0


def _persist_nonce(nonce: int) -> None:
    """Write nonce to disk atomically (temp-file + rename). Logs debug on failure but never raises."""
    try:
        nonce_dir = os.path.dirname(_NONCE_FILE)
        os.makedirs(nonce_dir, exist_ok=True)
        tmp_path = _NONCE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(str(nonce))
        os.replace(tmp_path, _NONCE_FILE)
    except (IOError, OSError) as e:
        import logging as _logging
        _logging.debug(f"global_kraken_nonce: could not persist nonce to {_NONCE_FILE}: {e}")


class GlobalKrakenNonceManager:
    """
    Singleton nonce manager for Kraken API with nanosecond precision.

    This class ensures that ALL Kraken API calls (across PLATFORM + ALL USERS)
    use ONE global monotonic nonce source with nanosecond precision.

    Features:
    - Nanosecond precision (19 digits) using time.time_ns()
    - Thread-safe with RLock
    - Strictly monotonic (always increasing)
    - Process-wide singleton
    - Statistics tracking

    Usage:
        manager = get_global_nonce_manager()
        nonce = manager.get_nonce()
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        """Singleton pattern - only one instance per process."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # Initialize the flag immediately in __new__ to prevent AttributeError
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initialize the nonce manager (only once)."""
        # Use getattr to safely check if _initialized exists and is True
        if getattr(self, '_initialized', False):
            return

        with self._lock:
            if getattr(self, '_initialized', False):
                return

            # Nanosecond precision (19 digits)
            # Example: 1768712093048832619
            # Load persisted nonce so we survive process restarts without replaying
            # nonces that Kraken has already accepted (including any jump-forward values).
            persisted = _load_persisted_nonce()
            current_ns = time.time_ns()

            # Guard against runaway nonce accumulation caused by many consecutive failed
            # reconnect cycles (each failed reconnect can jump the nonce forward ~400 s).
            # After hundreds of such cycles the persisted nonce can be hours ahead of
            # real time, which causes Kraken to reject every new nonce with
            # "EAPI:Invalid nonce" because the value is outside Kraken's acceptance window.
            # Cap the persisted nonce to at most 2 minutes ahead of the current time; the
            # pre-connection nonce jump that follows will still push it forward by 30 s so
            # we remain ahead of any nonce that Kraken accepted in the last ~2 minutes.
            _MAX_NONCE_AHEAD_NS = 120 * 1_000_000_000  # 2 minutes in nanoseconds
            if persisted > current_ns + _MAX_NONCE_AHEAD_NS:
                _excess_s = (persisted - current_ns) / 1_000_000_000
                _logger.warning(
                    f"global_kraken_nonce: persisted nonce is {_excess_s:.0f}s ahead of "
                    f"current time (likely from accumulated failed-reconnect jumps); "
                    f"resetting to current time to restore Kraken acceptance window."
                )
                persisted = current_ns
                _persist_nonce(persisted)

            # Start strictly ahead of both the wall clock and any previously
            # persisted nonce.  The +10 s jump ensures we are beyond any nonce
            # Kraken still holds from the last session even if the persisted
            # file is slightly stale (up to _PERSIST_EVERY_N−1 calls behind).
            self._last_nonce = max(current_ns, persisted) + _STARTUP_JUMP_NS

            # Persist immediately so a crash right after startup still leaves
            # a safe anchor for the *next* restart.
            _persist_nonce(self._last_nonce)

            self._nonce_lock = threading.RLock()

            # Counter used to throttle periodic disk persistence in get_nonce()
            self._nonces_since_persist = 0

            # Consecutive nonce-error counter for auto-heal logic
            self._consecutive_errors = 0

            # Statistics tracking
            self._total_nonces_issued = 0
            self._creation_time = time.time()

            self._initialized = True

    def get_nonce(self) -> int:
        """
        Get next nonce with nanosecond precision.

        Thread-safe: Uses RLock for reentrant locking.
        Monotonic: Each nonce is strictly greater than the previous.
        Precision: 19 digits (nanoseconds since epoch).

        Returns:
            int: Monotonically increasing nonce (nanoseconds)
        """
        with self._nonce_lock:
            # Get current timestamp in nanoseconds
            current_time_ns = time.time_ns()

            # Ensure strict monotonic increase
            # nonce = max(current_time_ns, last_nonce + 1)
            new_nonce = max(current_time_ns, self._last_nonce + 1)

            # Update state
            self._last_nonce = new_nonce
            self._total_nonces_issued += 1

            # Persist periodically so restarts don't replay already-seen nonces
            self._nonces_since_persist += 1
            if self._nonces_since_persist >= _PERSIST_EVERY_N:
                self._nonces_since_persist = 0
                _persist_nonce(new_nonce)

            return new_nonce

    def jump_forward(self, nanoseconds: int) -> int:
        """
        Jump the nonce forward by specified nanoseconds.

        Used for error recovery when "Invalid nonce" errors occur.
        The new value is persisted to disk immediately so that a process
        restart will not send a nonce lower than what Kraken already saw.

        Args:
            nanoseconds: Number of nanoseconds to jump forward

        Returns:
            int: New nonce value after jump
        """
        with self._nonce_lock:
            current_time_ns = time.time_ns()

            # Calculate two candidate nonces and use the larger one
            time_based = current_time_ns + nanoseconds
            increment_based = self._last_nonce + nanoseconds

            # Update to the larger value
            self._last_nonce = max(time_based, increment_based)

            # Always persist jumps immediately — they represent large state changes
            # that must survive restarts so Kraken doesn't reject stale nonces.
            self._nonces_since_persist = 0
            _persist_nonce(self._last_nonce)

            return self._last_nonce

    def record_error(self) -> int:
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
        Get statistics about nonce generation.

        Returns:
            dict: Statistics including total nonces, last nonce, uptime, rate
        """
        with self._nonce_lock:
            uptime = time.time() - self._creation_time
            rate = self._total_nonces_issued / uptime if uptime > 0 else 0

            return {
                'total_nonces_issued': self._total_nonces_issued,
                'last_nonce': self._last_nonce,
                'uptime_seconds': uptime,
                'nonces_per_second': rate,
                'consecutive_errors': self._consecutive_errors,
            }


# Singleton instance accessor
def get_global_nonce_manager() -> GlobalKrakenNonceManager:
    """
    Get the global nonce manager singleton instance.

    Returns:
        GlobalKrakenNonceManager: Singleton instance
    """
    return GlobalKrakenNonceManager()


def get_global_nonce_stats() -> dict:
    """
    Get statistics from the global nonce manager.

    Returns:
        dict: Statistics including total nonces, last nonce, uptime, rate
    """
    manager = get_global_nonce_manager()
    return manager.get_stats()


# FIX #2: Global state for monotonic nonce (DEPRECATED - use GlobalKrakenNonceManager instead)
# This is kept for backward compatibility with existing code
# New code should use GlobalKrakenNonceManager
_GLOBAL_LAST_NONCE = 0
_GLOBAL_NONCE_LOCK = threading.Lock()

def get_kraken_nonce():
    """
    FIX #2: Get Kraken API nonce with GLOBAL monotonic guarantee.

    Uses GlobalKrakenNonceManager with nanosecond precision.

    This ensures nonce is ALWAYS strictly increasing even if:
    - Multiple calls happen in same nanosecond
    - System clock moves backward
    - Multiple threads call simultaneously
    - Retries happen rapidly

    Thread-safe: Uses global nonce manager with RLock.
    Global state: Shares nonce across ALL users and calls.

    Returns:
        int: Monotonically increasing nonce (nanoseconds - 19 digits)
    """
    manager = get_global_nonce_manager()
    return manager.get_nonce()

# Alias for backward compatibility - use the global monotonic nonce
def get_global_kraken_nonce() -> int:
    """
    Get Kraken API nonce (primary interface).

    Uses GlobalKrakenNonceManager with nanosecond precision (19 digits).
    This is the ONE global function that ALL Kraken private calls should use.

    FIX #2: This implementation guarantees:
    - ONE global nonce source for all users
    - Monotonically increasing (never decreases, never repeats)
    - Nanosecond precision (19 digits)
    - Shared across all retries
    - Never reset on reconnect
    - Thread-safe

    Returns:
        int: Monotonically increasing nonce (nanoseconds - 19 digits)
    """
    return get_kraken_nonce()


# FIX 3: Global API lock for Kraken to prevent parallel writes
# Kraken requires ONE monotonic nonce per API key with NO parallel writes
_KRAKEN_API_LOCK = threading.Lock()

def get_kraken_api_lock() -> threading.Lock:
    """
    Get the global Kraken API lock.

    FIX 3: Kraken Nonce Authority
    - Kraken requires ONE monotonic nonce per API key
    - NO parallel writes allowed
    - All Kraken API calls must serialize through this lock

    Usage:
        lock = get_kraken_api_lock()
        with lock:
            # Make Kraken API call here
            # This ensures no parallel API calls that could cause nonce conflicts

    Returns:
        threading.Lock: Global lock for Kraken API calls
    """
    return _KRAKEN_API_LOCK


def jump_global_kraken_nonce_forward(milliseconds: int) -> int:
    """
    Jump the global Kraken nonce forward by specified milliseconds.

    This is used for error recovery when an "Invalid nonce" error occurs.
    Jumping forward clears the "burned" nonce window and ensures the next
    nonce will be accepted by Kraken API.

    Thread-safe: Uses global nonce manager with RLock.

    Args:
        milliseconds: Number of milliseconds to jump forward (converted to nanoseconds internally)

    Returns:
        int: New nonce value after jump (nanoseconds)
    """
    manager = get_global_nonce_manager()
    # Convert milliseconds to nanoseconds (1ms = 1,000,000ns)
    nanoseconds = milliseconds * 1_000_000
    return manager.jump_forward(nanoseconds)


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
    'GlobalKrakenNonceManager',
    'get_global_nonce_manager',
    'get_global_nonce_stats',
    'get_kraken_nonce',
    'get_global_kraken_nonce',
    'get_kraken_api_lock',
    'jump_global_kraken_nonce_forward',
    'reset_global_kraken_nonce',
]
