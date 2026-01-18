"""
NIJA Global Kraken Nonce Manager
=================================

ONE global monotonic nonce source shared across MASTER + ALL USERS.

This is the FINAL fix for Kraken nonce collisions:
- Single process-wide nonce generator
- Uses SIMPLE INCREMENT (+1) - NOT time-based, NOT auto-generated
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
    - Monotonic increment (not time-based) per Kraken requirements
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
    - Monotonic (strictly increasing nonces via simple +1 increment)
    - NOT time-based (uses increment, not time.time_ns() on every call)
    - Nanosecond-based initialization (time.time_ns() ONLY for initial value)
    - Process-wide singleton
    - No file persistence needed (monotonic increment guarantees increase)
    
    Thread Safety:
    - Uses threading.RLock for reentrant locking
    - Safe for concurrent calls from multiple threads
    - Safe for master + multiple user accounts
    
    Nonce Format:
    - Nanoseconds since epoch (19 digits)
    - Example: 1737159471234567890
    - Guaranteed unique via monotonic increment (not time-based)
    """
    
    def __init__(self):
        """
        Initialize the global nonce manager.
        
        IMPORTANT: This should only be called once via get_global_nonce_manager().
        Do not instantiate directly.
        
        The initial nonce is set using time.time_ns() ONCE.
        All subsequent nonces use simple +1 increment (NOT time-based).
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
        
        logger.info("Global Kraken Nonce Manager initialized (nanosecond precision)")
    
    def get_nonce(self) -> int:
        """
        Get the next monotonic nonce.
        
        Thread-safe: Uses lock to prevent race conditions.
        Monotonic: Each nonce is strictly greater than the previous.
        NOT time-based: Uses simple increment (not time.time_ns() on every call).
        
        Returns:
            int: Nonce in nanoseconds since epoch (19 digits)
        """
        with self._lock:
            # MONOTONIC INCREMENT - NOT TIME-BASED
            # Simply increment by 1 on each call
            # This is the CORRECT implementation per Kraken requirements
            self._last_nonce += 1
            nonce = self._last_nonce
            
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
    
    Implementation: Uses simple +1 increment (NOT time-based, NOT auto-generated).
    This meets Kraken's requirement for strictly monotonic nonces.
    
    Returns:
        int: Nonce in nanoseconds since epoch (monotonic increment)
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


__all__ = [
    'GlobalKrakenNonceManager',
    'get_global_nonce_manager',
    'get_global_kraken_nonce',
    'get_global_nonce_stats',
]
