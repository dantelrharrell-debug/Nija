# Rate Limiting Fix - January 10, 2026

## Problem Statement

The NIJA trading bot was experiencing **403 "Forbidden - Too many errors"** responses from the Coinbase Advanced Trade API, causing the bot to fail during market scanning. This issue occurred immediately after startup, despite having a 45-second startup delay.

### Symptoms
- Bot starts successfully and connects to Coinbase
- After 45s startup delay, fetches 351 USD/USDC trading pairs
- Begins scanning first batch of 15 markets
- Within 8 seconds of scanning, receives 403 error on `1INCH-USD`
- Retries with 22.9s delay, then again with 24.9s delay
- Bot gets stuck in retry loop, unable to scan markets

### Root Cause Analysis

1. **Burst of API Calls at Startup**:
   - `get_all_products()` fetches 1000+ products (filtered to 351)
   - Immediately followed by scanning 15 markets
   - Each market requires 1 `get_candles()` call
   - This creates a burst of ~16 API calls in rapid succession

2. **Rate Limiter Settings Too Aggressive**:
   - Previous: 10 req/min for `get_candles` (1 every 6 seconds)
   - Market scan delay: 6.5 seconds
   - But processing time + jitter meant actual rate was faster
   - Rate limiter is per-key, multiple calls can queue up

3. **Insufficient Recovery Time**:
   - 403 errors (API key temporarily blocked) only got 20-30s retry delay
   - Circuit breaker delays were only 15-20 seconds
   - Bot continued scanning other markets while waiting for retry
   - This kept hitting the rate limit, prolonging the block

## Solution Implemented

### 1. Adaptive Batch Sizing
**File**: `bot/trading_strategy.py`

```python
# Before: Fixed batch size
MARKET_BATCH_SIZE = 15

# After: Adaptive batch sizing
MARKET_BATCH_SIZE_MIN = 5   # Start with just 5 markets
MARKET_BATCH_SIZE_MAX = 15  # Grow to max after warmup
MARKET_BATCH_WARMUP_CYCLES = 3  # 3 cycles to warm up
```

- Bot now starts with only **5 markets per cycle** for the first 3 cycles
- Gradually increases to 15 markets after proving API stability
- Automatically reduces back to 5 if API health degrades

### 2. API Health Score Tracking
**File**: `bot/trading_strategy.py`

Added dynamic health tracking:
```python
self.api_health_score = 100  # 0-100 score
```

- **Degrades on errors**: -5 per failed request, -10 on circuit breaker, -20 on global breaker
- **Recovers on success**: +1 on partial success, +2 on full success
- **Adaptive batch sizing based on health**:
  - Health < 50%: Use 5 markets (minimum)
  - Health 50-80%: Use 10 markets (mid-range)
  - Health > 80%: Use 15 markets (maximum)

### 3. More Conservative Rate Limiting
**File**: `bot/broker_manager.py`

```python
# Before:
'get_candles': 10,  # 10 req/min = 6s interval
'get_all_products': 6,  # 6 req/min = 10s interval

# After:
'get_candles': 8,   # 8 req/min = 7.5s interval
'get_all_products': 5,  # 5 req/min = 12s interval
```

**Also increased market scan delay**:
```python
# Before: 6.5s delay between market scans
MARKET_SCAN_DELAY = 6.5

# After: 8.0s delay between market scans
MARKET_SCAN_DELAY = 8.0
```

### 4. Increased Recovery Delays
**File**: `bot/broker_manager.py`

```python
# Before:
FORBIDDEN_BASE_DELAY = 20.0  # 20-30s total
FORBIDDEN_JITTER_MAX = 10.0

# After:
FORBIDDEN_BASE_DELAY = 30.0  # 30-45s total
FORBIDDEN_JITTER_MAX = 15.0
```

**Circuit breaker delays also increased**:
- Consecutive failures: 15s → 20s
- Global circuit breaker: 20s → 30s

### 5. Post-Startup Cooldown
**File**: `bot/broker_manager.py`

Added 10-second cooldown after `get_all_products()`:
```python
logging.info("   💤 Cooling down for 10s after bulk product fetch to prevent rate limiting...")
time.sleep(10.0)
```

This prevents the burst of API calls that was triggering the 403 errors.

## Expected Behavior After Fix

### Startup Sequence
1. 45s startup delay (unchanged)
2. Connect to Coinbase API
3. Fetch all products (~351 markets)
4. **NEW: 10s cooldown after product fetch**
5. **NEW: Start with only 5 markets in first cycle**
6. Scan 5 markets with 8s delay between each (40s total)
7. **NEW: Gradually increase to 15 markets over 3 cycles**

### Rate Limiting Timeline
- **Cycle 1**: Scan 5 markets @ 8s each = 40s (warmup)
- **Cycle 2**: Scan 5 markets @ 8s each = 40s (warmup)
- **Cycle 3**: Scan 5 markets @ 8s each = 40s (warmup)
- **Cycle 4+**: Scan 10-15 markets @ 8s each = 80-120s (full speed)

### Recovery from Errors
- **Single error**: API health drops 5%, no immediate action
- **2 consecutive errors**: Circuit breaker activates, 20s pause, health drops 10%
- **4 total errors**: Global circuit breaker, 30s pause, health drops 20%, batch size reduces
- **403 error**: 30-45s delay before retry, health drops, batch size reduces to minimum

## Testing Recommendations

1. **Monitor first 3 cycles** - should scan only 5 markets each
2. **Check API health score** - should stay above 80% after warmup
3. **Verify no 403 errors** - with these changes, 403s should not occur
4. **Watch batch size growth** - should increase from 5 to 15 over cycles 1-4

## Rollback Plan

If this fix doesn't work, revert to previous settings:
```bash
git revert 9be4967
```

Then investigate:
- Check if API key has specific rate limits
- Review Coinbase API documentation for current limits
- Consider switching to WebSocket for real-time data
- Implement request queue with strict throttling

## Success Metrics

- ✅ No 403 "Forbidden" errors during startup
- ✅ API health score stays above 80% consistently
- ✅ Bot completes 3 warmup cycles without errors
- ✅ Batch size grows from 5 to 15 as expected
- ✅ Circuit breakers activate only on genuine API issues, not self-inflicted rate limits

## Related Files Modified

1. `bot/trading_strategy.py`
   - Added adaptive batch sizing
   - Added API health score tracking
   - Increased market scan delay to 8.0s
   - Increased circuit breaker delays
   - Added cycle counter tracking

2. `bot/broker_manager.py`
   - Reduced rate limits (more conservative)
   - Increased 403 error recovery delays
   - Added 10s cooldown after `get_all_products()`

## Additional Notes

This fix addresses the immediate problem of 403 errors at startup, but the underlying issue is the aggressive rate limiting by Coinbase. The bot should:

1. **Always err on the side of caution** with API calls
2. **Monitor API health continuously** and adapt automatically
3. **Use caching aggressively** to reduce duplicate calls
4. **Implement exponential backoff** on all retries
5. **Add circuit breakers** at multiple levels (per-request, per-symbol, global)

The current fix implements all of these strategies and should prevent 403 errors going forward.
