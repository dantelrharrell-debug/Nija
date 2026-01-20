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
    nonce = max(int(time.time() * 1000), last_nonce + 1)

Rules:
    ✅ Shared across all Kraken calls
    ✅ Shared across retries
    ✅ Shared across users
    ✅ Never stored per instance
    ✅ Never reset on reconnect
    ✅ Thread-safe with global lock
    ✅ Monotonically increasing

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

# FIX #2: Global state for monotonic nonce
# This is THE SINGLE SOURCE OF TRUTH for all Kraken nonces
# Never reset, never cleared, shared across all users
_GLOBAL_LAST_NONCE = 0
_GLOBAL_NONCE_LOCK = threading.Lock()

def get_kraken_nonce():
    """
    FIX #2: Get Kraken API nonce with GLOBAL monotonic guarantee.
    
    Returns max(current_timestamp_ms, last_nonce + 1)
    This ensures nonce is ALWAYS strictly increasing even if:
    - Multiple calls happen in same millisecond
    - System clock moves backward
    - Multiple threads call simultaneously
    - Retries happen rapidly
    
    Thread-safe: Uses global lock to prevent race conditions.
    Global state: Shares _GLOBAL_LAST_NONCE across ALL users and calls.
    
    Returns:
        int: Monotonically increasing nonce (milliseconds)
    """
    global _GLOBAL_LAST_NONCE
    
    with _GLOBAL_NONCE_LOCK:
        # Get current timestamp in milliseconds
        current_time_ms = int(time.time() * 1000)
        
        # FIX #2: Ensure strict monotonic increase
        # nonce = max(current_time, last_nonce + 1)
        # This guarantees EVERY nonce is larger than the previous
        new_nonce = max(current_time_ms, _GLOBAL_LAST_NONCE + 1)
        
        # Update global state
        _GLOBAL_LAST_NONCE = new_nonce
        
        return new_nonce

# Alias for backward compatibility - use the global monotonic nonce
def get_global_kraken_nonce() -> int:
    """
    Get Kraken API nonce (backward compatibility wrapper).
    
    Returns max(current_timestamp_ms, last_nonce + 1).
    This is the ONE global function that ALL Kraken private calls should use.
    
    FIX #2: This implementation guarantees:
    - ONE global nonce source for all users
    - Monotonically increasing (never decreases, never repeats)
    - Shared across all retries
    - Never reset on reconnect
    - Thread-safe
    
    Returns:
        int: Monotonically increasing nonce (milliseconds)
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


__all__ = [
    'get_kraken_nonce',
    'get_global_kraken_nonce',
    'get_kraken_api_lock',
]
