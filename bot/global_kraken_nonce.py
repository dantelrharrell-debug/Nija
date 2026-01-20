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
    from bot.global_kraken_nonce import get_global_kraken_nonce
    
    nonce = get_global_kraken_nonce()  # Always returns current timestamp in ms
"""

import time

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


__all__ = [
    'get_kraken_nonce',
    'get_global_kraken_nonce',
]
