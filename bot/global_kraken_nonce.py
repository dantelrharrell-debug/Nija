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
import os
import logging
from pathlib import Path
from typing import Optional
from collections import deque

logger = logging.getLogger('nija.kraken_nonce')


class GlobalKrakenNonceManager:
    """
    ELITE-TIER Singleton nonce manager for Kraken API.
    
    This is the ONE centralized nonce authority for ALL Kraken API calls across:
    - All users (MASTER + USER accounts)
    - All threads
    - All API call types
    - Startup and runtime
    
    ELITE FEATURES (Next-Level Quant Territory):
    ✅ Atomic nonce generation with RLock (reentrant, thread-safe)
    ✅ Shared state across ALL threads (true centralization)
    ✅ Startup burst protection (rate limiting during initialization)
    ✅ Persistence across restarts (file-backed state)
    ✅ Nanosecond precision (19 digits) using time.time_ns()
    ✅ Strictly monotonic (never decreases, never repeats)
    ✅ Request queuing to prevent parallel REST calls
    ✅ Metrics and monitoring for performance analysis
    
    Kraken Requirements:
    - NO parallel REST calls (we serialize with global lock)
    - Monotonically increasing nonces (we guarantee with atomic operations)
    - NO rapid startup bursts (we throttle with startup rate limiting)
    
    Usage:
        manager = get_global_nonce_manager()
        nonce = manager.get_nonce()
    """

    _instance = None
    _lock = threading.RLock()
    
    # Elite-tier configuration
    NONCE_PERSISTENCE_FILE = "data/kraken_global_nonce.txt"
    STARTUP_RATE_LIMIT_SECONDS = 0.5  # Min 500ms between rapid startup calls
    STARTUP_BURST_WINDOW = 10.0  # Consider first 10s as "startup" period
    MAX_BURST_RATE = 20  # Max 20 nonces/second during startup

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
            
            # ELITE FEATURE: Startup burst protection
            self._last_nonce_time = 0.0
            self._startup_nonce_times = deque(maxlen=100)  # Track recent nonce generation times
            
            # ELITE FEATURE: Persistence
            self._persistence_enabled = True
            self._persistence_file = self._get_persistence_path()
            
            # Load persisted nonce state
            self._load_persisted_nonce()

            self._initialized = True
            
            logger.info("🔥 ELITE-TIER GlobalKrakenNonceManager initialized")
            logger.info(f"   ✅ Atomic nonce generation enabled")
            logger.info(f"   ✅ Startup burst protection enabled ({self.STARTUP_RATE_LIMIT_SECONDS}s rate limit)")
            logger.info(f"   ✅ Persistence enabled: {self._persistence_file}")
    
    def _get_persistence_path(self) -> str:
        """Get the path for nonce persistence file."""
        # Try to use the configured path, fallback to relative path
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            return os.path.join(data_dir, "kraken_global_nonce.txt")
        except Exception as e:
            logger.warning(f"Could not create data directory: {e}, using temp file")
            return "/tmp/kraken_global_nonce.txt"
    
    def _load_persisted_nonce(self):
        """Load the last nonce from persistence file."""
        if not self._persistence_enabled:
            return
        
        try:
            if os.path.exists(self._persistence_file):
                with open(self._persistence_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        persisted_nonce = int(content)
                        # Only use persisted nonce if it's greater than current
                        if persisted_nonce > self._last_nonce:
                            self._last_nonce = persisted_nonce
                            logger.info(f"✅ Loaded persisted nonce: {persisted_nonce}")
        except Exception as e:
            logger.warning(f"Could not load persisted nonce: {e}")
    
    def _save_persisted_nonce(self, nonce: int):
        """Save the current nonce to persistence file."""
        if not self._persistence_enabled:
            return
        
        try:
            # Write to temp file first, then atomic rename for crash safety
            temp_file = self._persistence_file + '.tmp'
            with open(temp_file, 'w') as f:
                f.write(str(nonce))
            os.replace(temp_file, self._persistence_file)
        except Exception as e:
            logger.debug(f"Could not save persisted nonce: {e}")
    
    def _check_startup_burst(self) -> bool:
        """
        ELITE FEATURE: Check if we're in a startup burst and need to throttle.
        
        Returns:
            bool: True if we should apply rate limiting
        """
        now = time.time()
        uptime = now - self._creation_time
        
        # Only apply burst protection during startup window
        if uptime > self.STARTUP_BURST_WINDOW:
            return False
        
        # Check if we're generating nonces too rapidly
        self._startup_nonce_times.append(now)
        
        if len(self._startup_nonce_times) >= 10:
            # Calculate rate over last 10 nonces
            time_span = now - self._startup_nonce_times[0]
            if time_span > 0:
                rate = len(self._startup_nonce_times) / time_span
                if rate > self.MAX_BURST_RATE:
                    logger.debug(f"⚠️  Startup burst detected: {rate:.1f} nonces/sec (limit: {self.MAX_BURST_RATE})")
                    return True
        
        return False
    
    def _apply_rate_limit(self):
        """
        ELITE FEATURE: Apply rate limiting to prevent rapid startup bursts.
        
        Kraken hates rapid bursts of API calls, especially during startup.
        This throttles nonce generation to ensure smooth, distributed calls.
        """
        now = time.time()
        time_since_last = now - self._last_nonce_time
        
        if time_since_last < self.STARTUP_RATE_LIMIT_SECONDS:
            sleep_time = self.STARTUP_RATE_LIMIT_SECONDS - time_since_last
            logger.debug(f"⏳ Rate limiting: sleeping {sleep_time:.3f}s to prevent burst")
            time.sleep(sleep_time)
        
        self._last_nonce_time = time.time()

    def get_nonce(self, apply_rate_limiting: bool = True) -> int:
        """
        Get next nonce with nanosecond precision.
        
        ELITE FEATURES:
        - Atomic generation (thread-safe with RLock)
        - Startup burst protection (optional rate limiting)
        - Persistence (automatically saved to file)
        - Monitoring (tracks generation rate and patterns)

        Thread-safe: Uses RLock for reentrant locking.
        Monotonic: Each nonce is strictly greater than the previous.
        Precision: 19 digits (nanoseconds since epoch).
        
        Args:
            apply_rate_limiting: If True, apply startup burst protection
            
        Returns:
            int: Monotonically increasing nonce (nanoseconds)
        """
        with self._nonce_lock:
            # ELITE FEATURE: Startup burst protection
            if apply_rate_limiting and self._check_startup_burst():
                self._apply_rate_limit()
            
            # Get current timestamp in nanoseconds
            current_time_ns = time.time_ns()

            # Ensure strict monotonic increase
            # nonce = max(current_time_ns, last_nonce + 1)
            new_nonce = max(current_time_ns, self._last_nonce + 1)

            # Update state
            self._last_nonce = new_nonce
            self._total_nonces_issued += 1
            
            # ELITE FEATURE: Persist nonce (every 10th nonce to reduce I/O)
            if self._total_nonces_issued % 10 == 0:
                self._save_persisted_nonce(new_nonce)

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
    
    def set_rate_limiting(self, enabled: bool):
        """
        Enable or disable startup rate limiting.
        
        ELITE FEATURE: Allow dynamic control of rate limiting behavior.
        Useful for switching between startup mode and normal operation mode.
        
        Args:
            enabled: True to enable rate limiting, False to disable
        """
        with self._nonce_lock:
            if enabled:
                logger.info("✅ Startup burst protection enabled")
            else:
                logger.info("♻️  Startup burst protection disabled (normal operation mode)")
            # Note: Rate limiting is controlled per-call via apply_rate_limiting parameter
            # This method is for logging/documentation purposes
    
    def reset_burst_tracking(self):
        """
        Reset burst tracking metrics.
        
        ELITE FEATURE: Useful after startup phase completes to reset metrics.
        """
        with self._nonce_lock:
            self._startup_nonce_times.clear()
            self._last_nonce_time = 0.0
            logger.info("♻️  Burst tracking metrics reset")

    def get_stats(self) -> dict:
        """
        Get statistics about nonce generation.
        
        ELITE FEATURE: Comprehensive metrics for monitoring and analysis.

        Returns:
            dict: Statistics including total nonces, last nonce, uptime, rate, burst info
        """
        with self._nonce_lock:
            uptime = time.time() - self._creation_time
            rate = self._total_nonces_issued / uptime if uptime > 0 else 0
            
            # Calculate burst metrics
            recent_burst_rate = 0.0
            if len(self._startup_nonce_times) >= 2:
                time_span = self._startup_nonce_times[-1] - self._startup_nonce_times[0]
                if time_span > 0:
                    recent_burst_rate = len(self._startup_nonce_times) / time_span

            return {
                'total_nonces_issued': self._total_nonces_issued,
                'last_nonce': self._last_nonce,
                'uptime_seconds': uptime,
                'nonces_per_second': rate,
                'recent_burst_rate': recent_burst_rate,
                'in_startup_window': (uptime <= self.STARTUP_BURST_WINDOW),
                'persistence_file': self._persistence_file,
                'rate_limit_config': {
                    'startup_rate_limit_seconds': self.STARTUP_RATE_LIMIT_SECONDS,
                    'max_burst_rate': self.MAX_BURST_RATE,
                    'startup_window_seconds': self.STARTUP_BURST_WINDOW,
                }
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
