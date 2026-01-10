# Fix: "No key ... was found" Error Handling (Jan 10, 2026)

## Problem Statement

The NIJA trading bot was encountering errors when attempting to fetch candle data for invalid or delisted cryptocurrency pairs on Coinbase:

```
Error fetching candles: 'No key AACBR was found.'
Error fetching candles: 'No key YZCAY was found.'
```

## Root Cause

The Coinbase Advanced Trade API throws a custom error message `"'No key [SYMBOL] was found.'"` when attempting to fetch candle data for a product ID that doesn't exist or has been delisted.

The error handling logic in `bot/broker_manager.py` (CoinbaseBroker.get_candles method) was checking for several invalid symbol patterns:
- `'invalid' in error_str and ('product' in error_str or 'symbol' in error_str)`
- `'productid is invalid' in error_str`
- `'400' in error_str and 'invalid_argument' in error_str`

But it didn't recognize the `"No key ... was found"` pattern, so these errors were:
1. Logged as errors (causing log noise)
2. Potentially triggering retry logic
3. Could contribute to circuit breaker activation

## Solution

Added detection for the "No key ... was found" error pattern in the invalid symbol detection logic:

**File:** `bot/broker_manager.py`  
**Line:** 2431  

```python
is_no_key_error = 'no key' in error_str and 'was found' in error_str
is_invalid_symbol = has_invalid_keyword or is_productid_invalid or is_400_invalid_arg or is_no_key_error
```

## Impact

With this fix:
- ✅ Invalid symbols are detected and skipped immediately (no retries)
- ✅ Only logged at debug level (reduces log noise)
- ✅ Doesn't contribute to rate limit error counters
- ✅ Prevents circuit breaker activation from delisted coins
- ✅ Allows the bot to continue scanning other markets without interruption

## Testing

Created automated test: `test_no_key_error_fix.py`

Test results:
```
✅ All 11 tests passed
   - 'No key AACBR was found.' → Detected as invalid
   - 'No key YZCAY was found.' → Detected as invalid
   - ProductID errors → Detected as invalid
   - Rate limit errors → NOT detected as invalid (correct)
   - Network errors → NOT detected as invalid (correct)
```

## Related Documentation

- **Error Handling Strategy:** See `RATE_LIMIT_FIX_POSITION_CACHE_JAN_2026.md`
- **Invalid Symbol Handling:** See `INVALID_SYMBOL_FIX_SUMMARY.md`
- **Circuit Breaker Logic:** See `bot/broker_manager.py` lines 2423-2470

## Deployment

This is a safe, minimal change that:
- ✅ No breaking changes
- ✅ No new dependencies
- ✅ No configuration changes needed
- ✅ Backwards compatible with existing error handling

Safe to deploy immediately.

## Author

GitHub Copilot Agent - Jan 10, 2026
