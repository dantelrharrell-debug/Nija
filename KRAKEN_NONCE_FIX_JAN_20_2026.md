# Kraken "EAPI:Invalid nonce" Fix - January 20, 2026

## Problem Statement

The NIJA trading bot was experiencing a critical issue with Kraken API integration:

```
2026-01-20 16:59:28 | WARNING | ⚠️ Kraken API error fetching balance (MASTER): EAPI:Invalid nonce
2026-01-20 16:59:28 | ERROR |    ❌ No last known balance available, returning 0
2026-01-20 16:59:28 | INFO |    💰 KRAKEN Balance: $0.00
2026-01-20 16:59:28 | WARNING |    ⚠️  KRAKEN UNDERFUNDED
2026-01-20 16:59:28 | WARNING |       Current: $0.00
2026-01-20 16:59:28 | WARNING |       Minimum: $0.50
2026-01-20 16:59:28 | WARNING |    ❌ KRAKEN will NOT trade (add funds to enable)
```

### Impact
- Balance showing $0.00 instead of actual balance
- Kraken marked as underfunded
- Trading disabled due to perceived insufficient funds
- Bot unable to execute trades on Kraken

## Root Cause

When the global nonce manager (`_use_global_nonce=True`) was in use, the `_immediate_nonce_jump()` method did nothing when a nonce error was detected. It just logged a debug message and returned:

```python
if self._use_global_nonce:
    # Global nonce manager doesn't need jumps (nanosecond precision prevents collisions)
    logger.debug(f"   ⚡ Global nonce manager in use - no jump needed (nanosecond precision)")
    return
```

This was incorrect because:
1. The global nonce uses millisecond precision (not nanosecond)
2. Even with good precision, nonce errors can still occur (clock drift, concurrent requests, etc.)
3. When a nonce error happens, the nonce must be jumped forward to clear the "burned" nonce window
4. Without the jump, retry attempts would use similar nonces and continue to fail

## Solution

### 1. Added `jump_global_kraken_nonce_forward()` function

**File**: `bot/global_kraken_nonce.py`

```python
def jump_global_kraken_nonce_forward(milliseconds: int) -> int:
    """
    Jump the global Kraken nonce forward by specified milliseconds.
    
    This is used for error recovery when an "Invalid nonce" error occurs.
    Jumping forward clears the "burned" nonce window and ensures the next
    nonce will be accepted by Kraken API.
    """
    global _GLOBAL_LAST_NONCE
    
    with _GLOBAL_NONCE_LOCK:
        current_time_ms = int(time.time() * 1000)
        
        # Calculate two candidate nonces and use the larger one
        # This ensures the jump is effective even if:
        # - System time has advanced significantly (use time-based)
        # - Multiple rapid calls happen (use increment-based)
        # - Clock is adjusted backward (increment-based prevents going backward)
        time_based = current_time_ms + milliseconds
        increment_based = _GLOBAL_LAST_NONCE + milliseconds
        
        # Update to the larger of the two to maintain monotonic guarantee
        _GLOBAL_LAST_NONCE = max(time_based, increment_based)
        
        return _GLOBAL_LAST_NONCE
```

### 2. Updated `_immediate_nonce_jump()` method

**File**: `bot/broker_manager.py`

```python
def _immediate_nonce_jump(self):
    """
    Immediately jump nonce forward when a nonce error is detected.
    
    This method jumps the nonce forward by 120 seconds to clear the "burned"
    nonce window and ensure the next API call will succeed.
    """
    if self._use_global_nonce:
        # Use global nonce manager to jump forward
        if jump_global_kraken_nonce_forward is not None:
            immediate_jump_ms = 120 * 1000  # 120 seconds in milliseconds
            new_nonce = jump_global_kraken_nonce_forward(immediate_jump_ms)
            logger.debug(f"   ⚡ Immediately jumped GLOBAL nonce forward by 120s to clear burned nonce window (new nonce: {new_nonce})")
        else:
            logger.debug(f"   ⚡ Global nonce jump function not available - using time-based recovery")
        return
    # ... rest of method for fallback implementations
```

### 3. Updated imports

**File**: `bot/broker_manager.py`

```python
try:
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock, jump_global_kraken_nonce_forward
except ImportError:
    try:
        from global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock, jump_global_kraken_nonce_forward
    except ImportError:
        # Fallback: Global nonce manager not available
        get_global_kraken_nonce = None
        get_kraken_api_lock = None
        jump_global_kraken_nonce_forward = None
```

## How It Works

### Normal Flow
1. API call uses current nonce (e.g., 1768929491897)
2. Request succeeds
3. Balance is fetched correctly
4. Trading proceeds normally

### Error Recovery Flow
1. API call uses nonce (e.g., 1768929491897)
2. Kraken returns "EAPI:Invalid nonce" error
3. `_immediate_nonce_jump()` is called
4. Nonce is jumped forward by 120 seconds (120,000ms)
5. New nonce is 1768929611897 (120 seconds ahead)
6. Retry attempt uses jumped nonce
7. Kraken accepts the nonce
8. Balance is fetched successfully
9. Trading proceeds normally

## Testing

### Unit Test: `test_nonce_jump_fix.py`

Tests the core nonce jump functionality:
- ✅ Basic nonce generation is monotonic
- ✅ Nonce jump moves forward by correct amount
- ✅ Subsequent nonces remain monotonic after jump
- ✅ Multiple jumps work correctly

### Integration Test: `test_nonce_error_recovery.py`

Simulates the actual error scenario:
- ✅ Initial API call generates nonce
- ✅ Error detection triggers nonce jump
- ✅ Retry uses jumped nonce
- ✅ Success after recovery
- ✅ All nonces remain monotonic throughout

## Security Review

CodeQL security scan: **PASSED** (0 alerts)
- No security vulnerabilities introduced
- Thread-safe implementation with proper locking
- No race conditions or data corruption risks

## Expected Behavior After Fix

### Before Fix
```
EAPI:Invalid nonce → Retry with similar nonce → Error again → $0.00 balance → UNDERFUNDED
```

### After Fix
```
EAPI:Invalid nonce → Jump nonce by 120s → Retry with jumped nonce → SUCCESS → Actual balance → FUNDED
```

## Benefits

1. **Automatic Recovery**: Nonce errors are automatically recovered without manual intervention
2. **Minimal Delay**: 120-second jump is sufficient to clear the nonce window
3. **Monotonic Guarantee**: All nonces remain strictly increasing
4. **Thread-Safe**: Proper locking prevents race conditions
5. **Backward Compatible**: Falls back to per-user nonce if global manager unavailable

## Files Modified

1. `bot/global_kraken_nonce.py` - Added jump function
2. `bot/broker_manager.py` - Updated jump method and imports
3. `test_nonce_jump_fix.py` - Unit tests (NEW)
4. `test_nonce_error_recovery.py` - Integration tests (NEW)

## Deployment Notes

- No configuration changes required
- No environment variables needed
- No database migrations
- Works with existing credentials
- Backward compatible with fallback implementations

## Verification

To verify the fix is working in production:

1. Monitor logs for "EAPI:Invalid nonce" errors
2. If error occurs, look for:
   ```
   ⚡ Immediately jumped GLOBAL nonce forward by 120s to clear burned nonce window
   ```
3. Verify retry succeeds and balance is fetched correctly
4. Confirm Kraken shows as funded and trades execute

## Related Documentation

- `ISSUE_RESOLVED_KRAKEN_NONCE_JAN_18_2026.md` - Previous nonce fix
- `KRAKEN_NONCE_RESOLUTION_2026.md` - Nonce resolution history
- `GLOBAL_KRAKEN_NONCE_MANAGER_JAN_18_2026.md` - Global nonce manager implementation

## Summary

This fix ensures that when Kraken API returns an "Invalid nonce" error, the bot automatically jumps the nonce forward by 120 seconds, clearing the "burned" nonce window and allowing subsequent API calls to succeed. This prevents the bot from getting stuck with $0.00 balance errors and ensures trading can proceed normally.

**Status**: ✅ COMPLETE - All tests passing, security scan clean, ready for deployment
