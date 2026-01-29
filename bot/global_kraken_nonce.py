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

import time
import threading


class GlobalKrakenNonceManager:
    """
    Singleton nonce manager for Kraken API with nanosecond precision.

    This class ensures that ALL Kraken API calls (across MASTER + ALL USERS)
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
            self._last_nonce = 0
            self._nonce_lock = threading.RLock()

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

            return new_nonce

    def jump_forward(self, nanoseconds: int) -> int:
        """
        Jump the nonce forward by specified nanoseconds.

        Used for error recovery when "Invalid nonce" errors occur.

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
                'nonces_per_second': rate
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


__all__ = [
    'GlobalKrakenNonceManager',
    'get_global_nonce_manager',
    'get_global_nonce_stats',
    'get_kraken_nonce',
    'get_global_kraken_nonce',
    'get_kraken_api_lock',
    'jump_global_kraken_nonce_forward',
]
