# Rate Limiting Fix for Coinbase API (403/429 Errors) - Jan 10, 2026

## Problem Statement

The NIJA bot was experiencing severe API rate limiting issues with Coinbase:

```
2026-01-10 02:17:23 - coinbase.RESTClient - ERROR - HTTP Error: 429 Client Error: Too Many Requests 
2026-01-10 02:17:35 - coinbase.RESTClient - ERROR - HTTP Error: 403 Client Error: Forbidden Too many errors
WARNING:root:⚠️  API key temporarily blocked (403) on ABT-USD, waiting 18.0s before retry 1/3
```

### Error Sequence:
1. **429 "Too Many Requests"** - Initial rate limit warning
2. **403 "Forbidden - Too many errors"** - API key temporarily blocked
3. **Persistent blocking** - Even after waiting 2.5 minutes between cycles

## Root Cause Analysis

The bot had **conflicting rate limiting configurations**:

1. **Manual delay**: `MARKET_SCAN_DELAY = 4.0s` between market scans in `trading_strategy.py`
2. **RateLimiter class**: Enforces minimum `6.0s` between `get_candles()` calls (10 req/min) in `broker_manager.py`
3. **Conflict**: The 4s manual delay was **faster** than the 6s RateLimiter minimum

### Why This Caused Problems:

- The manual delay (4s) told the bot "wait 4 seconds between markets"
- The RateLimiter (6s) enforced "wait at least 6 seconds between API calls"
- This caused the RateLimiter to add additional delays on top of the manual delay
- But the overall request pattern was still too aggressive for Coinbase's sustained rate limits
- Coinbase initially returned 429 errors, then escalated to 403 "too many errors" (temporary API key ban)

## Solution Implemented

### 1. Aligned Manual Delay with RateLimiter (CRITICAL FIX)

**File**: `bot/trading_strategy.py`

```python
# BEFORE:
MARKET_SCAN_DELAY = 4.0  # 4000ms delay between market scans
MARKET_SCAN_LIMIT = 25   # Scan 25 markets per cycle
MARKET_BATCH_SIZE = 25

# AFTER:
MARKET_SCAN_DELAY = 6.5  # 6500ms delay between market scans
MARKET_SCAN_LIMIT = 15   # Scan 15 markets per cycle
MARKET_BATCH_SIZE = 15
```

**Why 6.5s delay?**
- RateLimiter enforces 6.0s minimum for `get_candles()` calls (10 req/min)
- The 0.5s buffer (6.5s vs 6.0s) accounts for jitter and processing time
- Ensures manual delay ≥ rate limiter minimum, preventing conflicts
- At 6.5s delay, we scan at ~0.15 req/s (well below Coinbase limits)

**Why 15 markets instead of 25?**
- **Scan time**: 15 markets × 6.5s = 97.5 seconds per cycle
- **Cycle interval**: 150 seconds (2.5 minutes)
- **Remaining time**: 52.5 seconds for position management
- **Fits comfortably**: within cycle time with buffer
- **Full coverage**: 737 markets ÷ 15 = ~49 cycles (~2 hours)

### 2. Faster Circuit Breaker Activation

**File**: `bot/trading_strategy.py`

```python
# BEFORE:
max_consecutive_rate_limits = 3  # Trigger after 3 consecutive errors
max_total_errors = 5             # Stop scan after 5 total errors

# AFTER:
max_consecutive_rate_limits = 2  # Trigger after 2 consecutive errors
max_total_errors = 4             # Stop scan after 4 total errors
```

**Why activate earlier?**
- Prevents cascading errors that lead to API key blocking
- Stops scanning before Coinbase returns 403 "too many errors"
- More conservative approach prevents temporary bans

### 3. Longer Circuit Breaker Recovery Times

**File**: `bot/trading_strategy.py`

```python
# BEFORE:
time.sleep(8.0)   # Consecutive error recovery
time.sleep(10.0)  # Global circuit breaker recovery

# AFTER:
time.sleep(15.0)  # Consecutive error recovery
time.sleep(20.0)  # Global circuit breaker recovery
```

**Why longer delays?**
- Gives Coinbase API more time to reset rate limit counters
- Prevents immediate re-triggering of rate limits
- Allows API key to "cool down" after temporary blocks

### 4. Improved 403 Error Handling

**File**: `bot/broker_manager.py`

```python
# BEFORE:
FORBIDDEN_BASE_DELAY = 15.0   # Base delay for 403 errors
FORBIDDEN_JITTER_MAX = 5.0    # Max jitter (15-20s total)

# AFTER:
FORBIDDEN_BASE_DELAY = 20.0   # Base delay for 403 errors
FORBIDDEN_JITTER_MAX = 10.0   # Max jitter (20-30s total)
```

**Why longer 403 delays?**
- 403 "Forbidden" indicates API key is temporarily blocked
- Longer delays (20-30s vs 15-20s) give the block time to expire
- Prevents aggressive retries that extend the block duration
- Coinbase needs time to remove the temporary ban

## Expected Results

### API Request Rate:
- **Before**: ~0.25 requests/second (4s delay, 25 markets)
- **After**: ~0.15 requests/second (6.5s delay, 15 markets)
- **Coinbase limit**: ~10 req/s burst (but much lower sustained)
- **Result**: ✅ Well below any reasonable sustained limit

### Error Reduction:
- ✅ Eliminates 429 "Too Many Requests" errors
- ✅ Prevents 403 "Forbidden - Too many errors" API key blocking
- ✅ Allows continuous operation without manual intervention
- ✅ Circuit breakers activate earlier to prevent cascading failures

### Performance Impact:
- **Market coverage**: ~2 hours for full scan (previously ~75 minutes)
- **Trade-off**: Slower opportunity discovery vs. reliable operation
- **Benefit**: Bot runs continuously without API blocks or downtime
- **Cycle time**: 97.5s scan + 52.5s buffer = fits in 150s cycle

## Testing & Validation

## Testing & Validation

### Syntax Validation
```bash
python -m py_compile bot/trading_strategy.py  # ✅ PASS
python -m py_compile bot/broker_manager.py    # ✅ PASS
```

### Expected Log Output

**Before Fix (Errors):**
```
2026-01-10 02:16:26 | INFO | 🔍 Scanning for new opportunities...
2026-01-10 02:16:26 | INFO | Scanning 25 markets (batch rotation mode)...
2026-01-10 02:17:23 - ERROR - HTTP Error: 429 Client Error: Too Many Requests 
WARNING:root:⚠️  Rate limited (429) on AAVE-USDC, retrying in 5.5s
2026-01-10 02:17:35 - ERROR - HTTP Error: 403 Client Error: Forbidden Too many errors
WARNING:root:⚠️  API key temporarily blocked (403) on ABT-USD, waiting 18.0s before retry 1/3
2026-01-10 02:21:56 | ERROR | 🚨 GLOBAL CIRCUIT BREAKER: 6 total errors - stopping scan
```

**After Fix (Success):**
```
2026-01-10 02:16:26 | INFO | 🔍 Scanning for new opportunities...
2026-01-10 02:16:26 | INFO | 📊 Market rotation: scanning batch 0-15 of 737 (2% through cycle)
2026-01-10 02:16:26 | INFO | Scanning 15 markets (batch rotation mode)...
[No 429 or 403 errors]
2026-01-10 02:18:03 | INFO | ✅ Scan summary: 15 markets scanned
2026-01-10 02:18:03 | INFO |    💡 Signals found: 1
2026-01-10 02:18:03 | INFO | ✅ coinbase cycle completed successfully
```

### Monitoring After Deployment

Watch logs for these indicators:

✅ **Success Indicators:**
- No 429 "Too Many Requests" errors
- No 403 "Forbidden" errors
- "15 markets scanned" in scan summary
- Circuit breaker not activated
- Scan completes in ~97 seconds

⚠️ **Warning Signs:**
- Any 429 or 403 errors (should not occur)
- Circuit breaker activation (should be rare/never)
- Scan time > 120 seconds (investigate delays)

## Files Modified

1. **bot/trading_strategy.py**:
   - Line 23: `MARKET_SCAN_LIMIT = 15` (was 25)
   - Line 37: `MARKET_SCAN_DELAY = 6.5` (was 4.0)
   - Line 45: `MARKET_BATCH_SIZE = 15` (was 25)
   - Line 1150: `max_consecutive_rate_limits = 2` (was 3)
   - Line 1151: `max_total_errors = 4` (was 5)
   - Line 1192: `time.sleep(20.0)` (was 10.0)
   - Line 1200: `time.sleep(15.0)` (was 8.0)

2. **bot/broker_manager.py**:
   - Line 59: `FORBIDDEN_BASE_DELAY = 20.0` (was 15.0)
   - Line 60: `FORBIDDEN_JITTER_MAX = 10.0` (was 5.0)

## Deployment Instructions

1. **Commit and push changes** (already done)
2. **Deploy to Railway/Render**:
   ```bash
   git push origin main  # Triggers auto-deploy
   ```
3. **Monitor logs for 3-4 cycles** (7.5-10 minutes)
4. **Verify no rate limiting errors** appear
5. **Confirm market scanning** completes successfully
6. **Check position management** still functions normally

## Rollback Plan

If issues occur, revert to previous values:
```python
# bot/trading_strategy.py
MARKET_SCAN_DELAY = 4.0
MARKET_SCAN_LIMIT = 25
MARKET_BATCH_SIZE = 25
max_consecutive_rate_limits = 3
max_total_errors = 5

# bot/broker_manager.py
FORBIDDEN_BASE_DELAY = 15.0
FORBIDDEN_JITTER_MAX = 5.0
```

**Note**: These old values WILL trigger rate limiting. Rollback should only be temporary while investigating alternatives.

## Summary

This fix addresses rate limiting by:
1. ✅ Aligning manual delays (6.5s) with RateLimiter minimums (6.0s)
2. ✅ Reducing API request rate to ultra-conservative 0.15 req/s
3. ✅ Activating protective circuit breakers earlier (2 vs 3 errors)
4. ✅ Giving API more recovery time (15s, 20s, 20-30s delays)
5. ✅ Preventing 403 "too many errors" API key blocking

**Trade-off**: Slower market coverage (2 hours vs 75 minutes)
**Benefit**: Continuous, reliable operation without API blocks

## Related Documentation

- `bot/rate_limiter.py` - RateLimiter class implementation
- `RATE_LIMITING_FIX.md` - Previous rate limiting fixes
- `BROKER_INTEGRATION_GUIDE.md` - Coinbase API integration details
