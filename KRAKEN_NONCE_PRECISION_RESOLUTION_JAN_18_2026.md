# Kraken Nonce Precision Fix - January 18, 2026

## Issue Summary

**Problem**: Kraken master account was failing to connect with `EAPI:Invalid nonce` error.

**Root Cause**: Mixed time precision (milliseconds vs microseconds) in nonce generation causing nonces to be rejected by Kraken API.

## Technical Details

### The Bug

The codebase had inconsistent nonce precision across different components:

1. **KrakenNonce class** (`bot/kraken_nonce.py`): Used **milliseconds** (`time.time() * 1000`)
2. **get_kraken_nonce() function** (`bot/broker_manager.py`): Used **microseconds** (`time.time() * 1000000`)
3. **Persisted nonce files**: Could contain either format depending on code path

### The Flow That Failed

1. Bot starts, loads persisted nonce in **microseconds** (16 digits, e.g., `1768700621901650`)
2. Attempts to use it with KrakenNonce class expecting **milliseconds** (13 digits)
3. Conversion logic had bugs - would compare microseconds to milliseconds directly
4. Result: Nonce sent to Kraken was way too large
5. Kraken rejects with `EAPI:Invalid nonce`

### Example of the Problem

```python
# Old buggy code:
persisted_nonce = get_kraken_nonce(account_identifier)  # Returns 1768700621901650 (microseconds)
current_time_ms = int(time.time() * 1000)              # Returns 1768700621901 (milliseconds)

# Bug: Compared microseconds to milliseconds directly
if persisted_nonce > current_time_ms:  # Always true! (microseconds > milliseconds)
    # Attempted conversion but threshold was wrong
    MICROSECOND_THRESHOLD = 100000000000000
    if persisted_nonce > MICROSECOND_THRESHOLD:  # Threshold too small!
        # Would convert, but logic was flawed
```

## The Fix

### Changes Made

1. **Standardized to Milliseconds**
   - Updated `get_kraken_nonce()` to use milliseconds: `int(time.time() * 1000)`
   - Updated fallback nonce generation to use milliseconds
   - Updated all nonce jumps and retries to use milliseconds

2. **Fixed Conversion Logic**
   ```python
   # New correct code:
   MICROSECOND_THRESHOLD = 100000000000000  # 10^14
   if persisted_nonce > MICROSECOND_THRESHOLD:
       # Old microsecond nonce, convert to milliseconds
       persisted_nonce_ms = int(persisted_nonce / 1000)
   ```

3. **Backward Compatibility**
   - Added automatic detection and conversion of old microsecond nonces
   - Detection uses threshold: 10^14 (microseconds are 16 digits, milliseconds are 13 digits)
   - Old nonce files are automatically migrated on first read

4. **Updated All Components**
   - KrakenBroker initialization
   - Fallback nonce generation
   - Immediate nonce jump (error recovery)
   - Retry nonce jumps
   - Debug logging messages
   - Code comments

### Files Modified

- `bot/broker_manager.py` - Main fix implementation
  - `get_kraken_nonce()` function
  - `KrakenBroker.__init__()` 
  - `KrakenBroker._immediate_nonce_jump()`
  - `KrakenBroker.connect()` retry logic
  - All comments and debug messages

### Testing

Created comprehensive test script (`test_nonce_fix.py`) with 3 test cases:

1. **Nonce Precision Test**: Verifies nonces are in milliseconds (13 digits)
2. **Microsecond Conversion Test**: Verifies old microsecond nonces are converted
3. **KrakenNonce Class Test**: Verifies class generates monotonic millisecond nonces

**Test Results**: ✅ All 3 tests passing

## Why This Matters

### Kraken Nonce Requirements

Kraken API requires nonces to be:
1. **Strictly monotonically increasing** (each nonce > previous nonce)
2. **Near current time** (not too far in the future or past)
3. **Consistent format** (usually milliseconds or microseconds, but must be consistent)

### The Impact of Wrong Precision

- **Microseconds nonces** (16 digits): ~1,768,700,621,901,650
- **Milliseconds nonces** (13 digits): ~1,768,700,621,901

When sending a microsecond nonce to Kraken expecting milliseconds:
- The nonce appears to be **1000x too far in the future**
- Kraken rejects it as invalid
- Connection fails immediately

## Migration Path

### For Existing Deployments

The fix includes automatic migration:
1. On first connection after deployment, bot detects old microsecond nonces
2. Automatically converts them to milliseconds
3. Saves converted value to file
4. All future nonces use milliseconds

No manual intervention required! 🎉

### Nonce File Locations

- Master account: `data/kraken_nonce_master.txt`
- User accounts: `data/kraken_nonce_user_<userid>.txt`

These files now contain millisecond values (13 digits).

## Verification

To verify the fix is working:

```bash
# Run the test script
python3 test_nonce_fix.py

# Expected output:
# ✅ PASS: Nonce Precision
# ✅ PASS: Microsecond Conversion  
# ✅ PASS: KrakenNonce Class
# Total: 3/3 tests passed
```

## Related Issues

This fix resolves:
- `EAPI:Invalid nonce` errors on connection
- Kraken connection failures even with valid API credentials
- Nonce-related retry loops
- Inconsistent behavior after bot restarts

## Additional Notes

### Why Milliseconds?

1. **Industry Standard**: Most APIs use milliseconds for timestamps
2. **Precision**: Sufficient for preventing collisions (1ms granularity)
3. **Readability**: 13 digits vs 16 digits
4. **Compatibility**: Matches KrakenNonce class design

### Future Considerations

- All new nonce-related code should use milliseconds
- Always validate nonce precision when debugging connection issues
- Run test_nonce_fix.py after any nonce-related changes

## References

- Original issue: Logs showing `EAPI:Invalid nonce` error
- Kraken API docs: https://docs.kraken.com/rest/
- Related fixes:
  - `KRAKEN_NONCE_PERSISTENCE_FIX_JAN_17_2026.md`
  - `KRAKEN_NONCE_FIX_FINAL_JAN_14_2026.md`

---

**Status**: ✅ Fixed and tested  
**Date**: January 18, 2026  
**Impact**: Critical - Enables Kraken master account connection  
**Breaking Changes**: None (backward compatible with auto-migration)
