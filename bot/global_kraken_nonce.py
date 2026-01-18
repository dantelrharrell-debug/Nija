"""
NIJA Global Kraken Nonce Manager
=================================

ONE global monotonic nonce source shared across MASTER + ALL USERS.

This is the FINAL fix for Kraken nonce collisions:
- Single process-wide nonce generator
- Uses time.time_ns() (nanoseconds) for maximum precision
- Thread-safe with proper locking
- Guarantees strict monotonic increase across all users
- No per-user nonce files needed
- Scales safely to 10-100 users

Usage:
    from bot.global_kraken_nonce import get_global_kraken_nonce
    
    nonce = get_global_kraken_nonce()  # Thread-safe, monotonic

Architecture:
    - ONE singleton instance per process
    - ALL Kraken API calls (master + users) share this single nonce source
    - No nonce collisions possible (single source of truth)
    - Simple, reliable, production-safe
"""

import time
import threading
from typing import Optional

import logging

logger = logging.getLogger('nija.kraken_nonce')


class GlobalKrakenNonceManager:
    """
    Global Kraken nonce manager - ONE instance shared across all users.
    
    Features:
    - Thread-safe (uses RLock for reentrant locking)
    - Monotonic (strictly increasing nonces)
    - Nanosecond precision (time.time_ns())
    - Process-wide singleton
    - No file persistence needed (nanosecond timestamps always increase)
    - OPTIONAL: Process-level API call serialization (Option B)
    
    Thread Safety:
    - Uses threading.RLock for reentrant locking
    - Safe for concurrent calls from multiple threads
    - Safe for master + multiple user accounts
    
    Nonce Format:
    - Nanoseconds since epoch (19 digits)
    - Example: 1737159471234567890
    - Guaranteed unique even at high request rates
    
    API Call Serialization (Option B):
    - Additional global lock to serialize ALL Kraken API calls
    - Ensures only ONE API call happens at a time across ALL users
    - Prevents any possible nonce collision or race condition
    - Can be enabled via enable_api_serialization()
    """
    
    def __init__(self):
        """
        Initialize the global nonce manager.
        
        IMPORTANT: This should only be called once via get_global_nonce_manager().
        Do not instantiate directly.
        """
        # Use RLock (reentrant lock) for thread-safety
        # RLock allows the same thread to acquire the lock multiple times
        self._lock = threading.RLock()
        
        # Last issued nonce (nanoseconds since epoch)
        # Initialize to current time to ensure we never go backwards
        self._last_nonce = time.time_ns()
        
        # Statistics for monitoring
        self._total_nonces_issued = 0
        self._initialized_at = time.time()
        
        # API call serialization lock (Option B)
        # This lock can be used to serialize ALL Kraken API calls
        # across MASTER + ALL USERS to prevent any possible race conditions
        self._api_call_lock = threading.RLock()
        self._api_serialization_enabled = True  # Enabled by default for maximum safety
        
        logger.info("Global Kraken Nonce Manager initialized (nanosecond precision, API serialization: ENABLED)")
    
    def get_api_call_lock(self) -> threading.RLock:
        """
        Get the global API call lock for serializing Kraken API calls.
        
        This implements Option B from the requirements: Kraken-only process lock
        that serializes all Kraken API calls, one at a time, with guaranteed
        increasing nonce.
        
        Usage:
            manager = get_global_nonce_manager()
            with manager.get_api_call_lock():
                # Make Kraken API call here
                # Only ONE call will execute at a time across ALL users
                result = api.query_private(method, params)
        
        Returns:
            threading.RLock: The global API call lock
        """
        return self._api_call_lock
    
    def enable_api_serialization(self):
        """
        Enable API call serialization (default: enabled).
        
        When enabled, all Kraken API calls should use get_api_call_lock()
        to ensure only one call happens at a time.
        """
        with self._lock:
            self._api_serialization_enabled = True
            logger.info("✅ Kraken API call serialization ENABLED")
    
    def disable_api_serialization(self):
        """
        Disable API call serialization (not recommended).
        
        WARNING: Disabling API serialization may cause nonce collisions
        in high-concurrency scenarios. Only disable for testing.
        """
        with self._lock:
            self._api_serialization_enabled = False
            logger.warning("⚠️ Kraken API call serialization DISABLED (not recommended)")
    
    def is_api_serialization_enabled(self) -> bool:
        """
        Check if API call serialization is enabled.
        
        Returns:
            bool: True if API serialization is enabled
        """
        with self._lock:
            return self._api_serialization_enabled
    
    def get_nonce(self) -> int:
        """
        Get the next monotonic nonce.
        
        Thread-safe: Uses lock to prevent race conditions.
        Monotonic: Each nonce is strictly greater than the previous.
        
        Returns:
            int: Nonce in nanoseconds since epoch (19 digits)
        """
        with self._lock:
            # Get current time in nanoseconds
            current_ns = time.time_ns()
            
            # Ensure strictly monotonic increase
            # If time hasn't advanced, increment by 1 nanosecond
            if current_ns <= self._last_nonce:
                nonce = self._last_nonce + 1
            else:
                nonce = current_ns
            
            # Update last nonce
            self._last_nonce = nonce
            
            # Update statistics
            self._total_nonces_issued += 1
            
            return nonce
    
    def get_stats(self) -> dict:
        """
        Get statistics about nonce generation.
        
        Returns:
            dict: Statistics including total nonces issued, uptime, etc.
        """
        with self._lock:
            uptime_seconds = time.time() - self._initialized_at
            
            return {
                'last_nonce': self._last_nonce,
                'total_nonces_issued': self._total_nonces_issued,
                'uptime_seconds': uptime_seconds,
                'nonces_per_second': self._total_nonces_issued / uptime_seconds if uptime_seconds > 0 else 0,
                'initialized_at': self._initialized_at,
                'api_serialization_enabled': self._api_serialization_enabled,
            }
    
    def reset_for_testing(self):
        """
        Reset the nonce manager (for testing only).
        
        WARNING: Do not call this in production code!
        This is only for unit tests.
        """
        with self._lock:
            self._last_nonce = time.time_ns()
            self._total_nonces_issued = 0
            logger.warning("⚠️ Global Kraken Nonce Manager reset (testing only)")


# Global singleton instance
_global_nonce_manager: Optional[GlobalKrakenNonceManager] = None
_init_lock = threading.Lock()


def get_global_nonce_manager() -> GlobalKrakenNonceManager:
    """
    Get the global Kraken nonce manager instance (singleton).
    
    This function is thread-safe and ensures only one instance exists
    per process. All Kraken API calls (master + users) should use this
    single instance.
    
    Returns:
        GlobalKrakenNonceManager: The global singleton instance
    """
    global _global_nonce_manager
    
    with _init_lock:
        if _global_nonce_manager is None:
            _global_nonce_manager = GlobalKrakenNonceManager()
        return _global_nonce_manager


def get_global_kraken_nonce() -> int:
    """
    Get the next global Kraken nonce (convenience function).
    
    This is the main function that all Kraken API calls should use.
    It's thread-safe and guarantees monotonic nonces across all users.
    
    Returns:
        int: Nonce in nanoseconds since epoch
    """
    manager = get_global_nonce_manager()
    return manager.get_nonce()


def get_global_nonce_stats() -> dict:
    """
    Get statistics about global nonce generation.
    
    Returns:
        dict: Statistics including total nonces issued, uptime, etc.
    """
    manager = get_global_nonce_manager()
    return manager.get_stats()


def get_kraken_api_lock() -> threading.RLock:
    """
    Get the global Kraken API call lock (Option B: Serialization).
    
    This lock should be used to wrap ALL Kraken API calls to ensure
    only ONE call executes at a time across MASTER + ALL USERS.
    
    This implements Option B from requirements: Kraken-only process lock
    that serializes all Kraken API calls one at a time with guaranteed
    increasing nonce.
    
    Usage:
        from bot.global_kraken_nonce import get_kraken_api_lock
        
        with get_kraken_api_lock():
            # Make Kraken API call here
            result = api.query_private(method, params)
    
    Returns:
        threading.RLock: The global API call lock
    """
    manager = get_global_nonce_manager()
    return manager.get_api_call_lock()


__all__ = [
    'GlobalKrakenNonceManager',
    'get_global_nonce_manager',
    'get_global_kraken_nonce',
    'get_global_nonce_stats',
    'get_kraken_api_lock',
]
