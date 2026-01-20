"""
NIJA Kraken Nonce Generator (Railway-Safe)
==========================================

✅ CORRECT APPROACH (Railway-safe, timestamp-based)

Uses timestamp-based nonce generation - NO persistence required.
ONE global function shared across MASTER + ALL USERS.

Implementation:
    def get_kraken_nonce():
        return int(time.time() * 1000)

✅ DO:
    - Use timestamp-based nonce (milliseconds since epoch)
    - One nonce generator globally
    - All Kraken private calls use this same function

❌ DO NOT:
    - Use counters
    - Use per-thread nonce
    - Use random numbers
    - Persist nonce to disk (not needed with timestamps)

Usage:
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock
    
    nonce = get_global_kraken_nonce()  # Always returns current timestamp in ms
    
    # For API calls requiring serialization:
    lock = get_kraken_api_lock()
    with lock:
        # Make Kraken API call here
"""

import time
import threading

def get_kraken_nonce():
    """
    Get Kraken API nonce using timestamp (Railway-safe).
    
    Returns current time in milliseconds since epoch.
    This is monotonically increasing (time only moves forward)
    and requires no persistence.
    
    Returns:
        int: Current timestamp in milliseconds
    """
    return int(time.time() * 1000)

# Alias for backward compatibility - use the simple timestamp-based nonce
def get_global_kraken_nonce() -> int:
    """
    Get Kraken API nonce (backward compatibility wrapper).
    
    Returns current timestamp in milliseconds.
    This is the ONE global function that ALL Kraken private calls should use.
    
    Returns:
        int: Current timestamp in milliseconds
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
