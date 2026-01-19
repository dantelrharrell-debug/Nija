"""
NIJA Global Kraken Nonce Manager
=================================

ONE global monotonic nonce source shared across MASTER + ALL USERS.

This is the FINAL fix for Kraken nonce collisions:
- Single process-wide nonce generator
- Uses PERSISTENT storage (survives restarts)
- Thread-safe with proper locking
- Guarantees strict monotonic increase across all users
- Correct Kraken nonce formula: max(last_nonce + 1, current_timestamp_ns)
- Scales safely to 10-100 users

Usage:
    from bot.global_kraken_nonce import get_global_kraken_nonce
    
    nonce = get_global_kraken_nonce()  # Thread-safe, monotonic, persistent

Architecture:
    - ONE singleton instance per process
    - ALL Kraken API calls (master + users) share this single nonce source
    - Nonce persisted to disk at: data/kraken_global_nonce.txt
    - No nonce collisions possible (single source of truth)
    - Survives process restarts
    - Monotonic increment with current time check per Kraken requirements
"""

import time
import threading
import os
from typing import Optional

import logging

logger = logging.getLogger('nija.kraken_nonce')

# Data directory for nonce persistence
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
os.makedirs(_data_dir, exist_ok=True)


class GlobalKrakenNonceManager:
    """
    Global Kraken nonce manager - ONE instance shared across all users.
    
    Features:
    - Thread-safe (uses RLock for reentrant locking)
    - Monotonic (strictly increasing nonces via formula: max(last_nonce + 1, current_timestamp_ns))
    - Persistent (survives process restarts via disk storage)
    - Nanosecond-based precision (time.time_ns())
    - Process-wide singleton
    - API call serialization (Option B)
    
    Thread Safety:
    - Uses threading.RLock for reentrant locking
    - Safe for concurrent calls from multiple threads
    - Safe for master + multiple user accounts
    
    Nonce Formula (Per Kraken Requirements):
    - nonce = max(last_nonce + 1, current_timestamp_ns)
    - This ensures:
      1. Always monotonically increasing
      2. Never goes backwards (even on clock drift)
      3. Stays close to current time (Kraken requirement)
      4. Survives restarts safely
    
    Persistence:
    - Nonce saved to disk after each generation
    - File: data/kraken_global_nonce.txt
    - Loaded on startup to resume from last value
    - Thread-safe file operations
    
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
        Initialize the global nonce manager with persistent storage.
        
        IMPORTANT: This should only be called once via get_global_nonce_manager().
        Do not instantiate directly.
        
        The initial nonce is loaded from disk (if exists) or set using current timestamp.
        All subsequent nonces use simple +1 increment (NOT time-based).
        Nonce is persisted to disk after each generation for restart safety.
        """
        # Use RLock (reentrant lock) for thread-safety
        # RLock allows the same thread to acquire the lock multiple times
        self._lock = threading.RLock()
        
        # Nonce persistence file path
        self._nonce_file = os.path.join(_data_dir, 'kraken_global_nonce.txt')
        
        # Load last nonce from disk or initialize with current time
        self._last_nonce = self._load_nonce_from_disk()
        
        # Statistics for monitoring
        self._total_nonces_issued = 0
        self._initialized_at = time.time()
        
        # API call serialization lock (Option B)
        # This lock can be used to serialize ALL Kraken API calls
        # across MASTER + ALL USERS to prevent any possible race conditions
        self._api_call_lock = threading.RLock()
        self._api_serialization_enabled = True  # Enabled by default for maximum safety
        
        logger.info(f"Global Kraken Nonce Manager initialized (persisted nonce: {self._last_nonce}, API serialization: ENABLED)")
    
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
    
    def _load_nonce_from_disk(self) -> int:
        """
        Load the last nonce from disk.
        
        Uses the correct nonce formula: max(last_nonce + 1, current_timestamp_ms)
        This ensures nonces are always monotonically increasing and restart-safe.
        
        Returns:
            int: Initial nonce value (nanoseconds since epoch)
        """
        current_time_ns = time.time_ns()
        
        if os.path.exists(self._nonce_file):
            try:
                with open(self._nonce_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        persisted_nonce = int(content)
                        # Use the formula: max(last_nonce + 1, current_timestamp)
                        # This ensures we never go backwards even on clock adjustments
                        initial_nonce = max(persisted_nonce + 1, current_time_ns)
                        logger.info(f"Loaded persisted nonce: {persisted_nonce}, using: {initial_nonce}")
                        return initial_nonce
            except (ValueError, IOError) as e:
                logger.warning(f"Could not load persisted nonce: {e}, using current time")
        
        # No persisted nonce or error loading - use current time
        logger.info(f"No persisted nonce found, initializing with current time: {current_time_ns}")
        return current_time_ns
    
    def _persist_nonce_to_disk(self, nonce: int):
        """
        Persist the nonce to disk for restart safety.
        
        This is called after each nonce generation to ensure the state
        survives process restarts.
        
        Args:
            nonce: The nonce value to persist
        """
        try:
            with open(self._nonce_file, 'w') as f:
                f.write(str(nonce))
        except IOError as e:
            # Log but don't fail - nonce generation can continue
            logger.debug(f"Could not persist nonce to disk: {e}")
    
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
        Get the next monotonic nonce with persistence.
        
        Thread-safe: Uses lock to prevent race conditions.
        Monotonic: Each nonce is strictly greater than the previous.
        Persistent: Saved to disk after each generation.
        
        Uses the correct Kraken nonce formula:
        nonce = max(last_nonce + 1, current_timestamp_ms)
        
        Returns:
            int: Nonce in nanoseconds since epoch (19 digits)
        """
        with self._lock:
            # Get current timestamp
            current_time_ns = time.time_ns()
            
            # Apply the correct nonce formula: max(last_nonce + 1, current_timestamp)
            # This ensures:
            # 1. Nonce always increases monotonically
            # 2. Nonce stays close to current time (Kraken requirement)
            # 3. No collisions even on rapid restarts
            self._last_nonce = max(self._last_nonce + 1, current_time_ns)
            nonce = self._last_nonce
            
            # Persist to disk for restart safety
            self._persist_nonce_to_disk(nonce)
            
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
            # Clear persisted nonce file
            try:
                if os.path.exists(self._nonce_file):
                    os.remove(self._nonce_file)
            except Exception as e:
                logger.debug(f"Could not remove nonce file during reset: {e}")
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
    
    Implementation: Uses formula max(last_nonce + 1, current_timestamp_ns)
    This meets Kraken's requirement for strictly monotonic nonces and
    ensures nonces stay close to current time.
    
    Persistence: Nonce is saved to disk after each generation for restart safety.
    
    Returns:
        int: Nonce in nanoseconds since epoch (monotonic, persistent)
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
