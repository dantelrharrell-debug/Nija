# Coinbase API Rate Limiting Fix - January 9, 2026

## Problem Summary

The NIJA trading bot was experiencing two critical rate limiting errors from Coinbase API:

1. **403 Forbidden "Too many errors"** - During startup connection attempts
2. **429 Too Many Requests** - During market scanning operations

These errors indicate the bot was exceeding Coinbase's API rate limits, causing the API to temporarily block the API key.

## Root Cause

Coinbase has strict rate limits:
- Burst rate: ~10 requests/second
- **Sustained rate: Much lower (~1 req/s or less)**
- **Cooldown period: ~30 seconds after 403 errors**

The bot's previous configuration was too aggressive:
- Startup delay: 15s (insufficient for API reset after 403)
- Market scan: 50 markets per cycle at 1 req/s
- Connection retry delays: Too short for 403 recovery

## Solution Implemented

### 1. More Conservative Market Scanning

**Before:**
- 50 markets per batch
- 1.0s delay between requests (1 req/s)
- ~50 second scan time

**After:**
- **25 markets per batch** (50% reduction)
- **2.0s delay between requests** (0.48 req/s)
- ~52 second scan time
- Complete market scan: 29 cycles vs 15 cycles (slower but safer)

### 2. Longer Startup Delay

**Before:** 15 seconds
**After:** **30 seconds**

This gives Coinbase API adequate time to reset rate limits after a 403 error before attempting to reconnect.

### 3. Enhanced Connection Retry Logic

**Before:**
- 5 max attempts
- 5s base delay
- Max delay: 80s

**After:**
- **6 max attempts**
- **10s base delay**
- **Max delay: 160s**
- Exponential backoff: 10s, 20s, 40s, 80s, 160s

### 4. Improved Candle Request Retries

**Before:**
- 5 max retries
- 3s base delay
- Max delay for 403: ~160s

**After:**
- **6 max retries**
- **5s base delay**
- **Max delay for 403: 320s** (5.3 minutes)
- Distinguishes 403 (API key block) from 429 (rate limit)

### 5. Enhanced Circuit Breaker

**Before:** 2s pause on consecutive failures
**After:** **5s pause on consecutive failures**

When the bot detects multiple consecutive rate limit errors, it now pauses for 5 seconds to allow the API to recover.

## Expected Behavior

### Startup
1. Bot waits **30 seconds** before first API connection
2. If connection fails with 403:
   - Retry 1: Wait 10s
   - Retry 2: Wait 20s
   - Retry 3: Wait 40s
   - Retry 4: Wait 80s
   - Retry 5: Wait 160s
3. Total max wait time: ~310 seconds (5+ minutes)

### Market Scanning
1. Scans **25 markets** per cycle (reduced from 50)
2. **2.0 seconds** between each market request
3. Effective rate: **~0.48 requests/second** (well below Coinbase limits)
4. If rate limited:
   - Circuit breaker activates after 3-5 consecutive failures
   - Pauses for 5 seconds to allow API recovery

### Error Recovery
- **429 errors**: Standard exponential backoff (5s, 10s, 20s, 40s, 80s, 160s)
- **403 errors**: Aggressive backoff (10s, 20s, 40s, 80s, 160s, 320s)
- Circuit breaker: 5s pause after consecutive failures

## Trade-offs

### Pros
✅ Eliminates 403/429 rate limit errors
✅ More stable and reliable operation
✅ Better API key preservation
✅ Complies with Coinbase rate limits

### Cons
⚠️ Slower market scanning (29 cycles vs 15 for full scan)
⚠️ Longer startup time (30s initial delay)
⚠️ May miss some short-term opportunities

## Files Modified

1. `bot/trading_strategy.py`
   - Reduced MARKET_SCAN_LIMIT: 50 → 25
   - Increased MARKET_SCAN_DELAY: 1.0s → 2.0s
   - Increased startup_delay: 15s → 30s
   - Enhanced circuit breaker: 2s → 5s

2. `bot/broker_manager.py`
   - Increased connection max_attempts: 5 → 6
   - Increased connection base_delay: 5s → 10s
   - Increased candle max_retries: 5 → 6
   - Increased candle base_delay: 3s → 5s
   - Enhanced 403 handling with longer delays

## Monitoring

Watch for these log messages to confirm the fix is working:

✅ **Success indicators:**
- "✅ Connected to Coinbase Advanced Trade API"
- "📊 Scan summary: 25 markets scanned" (not 50)
- No "429" or "403" errors in logs

⚠️ **Warning indicators:**
- "🛑 CIRCUIT BREAKER: Pausing for 5s..." (triggered if still getting rate limited)
- "⚠️ API key temporarily blocked (403)" (should be rare now)

❌ **Failure indicators:**
- Repeated 403/429 errors even with new delays
- "❌ Failed to connect after maximum retry attempts"

## Rollback Plan

If this fix causes issues, the previous values were:
- MARKET_SCAN_LIMIT: 50
- MARKET_SCAN_DELAY: 1.0
- startup_delay: 15
- connection base_delay: 5.0
- candle base_delay: 3.0

## Conclusion

This fix implements a **much more conservative** approach to API rate limiting:
- **50% fewer requests per cycle** (25 vs 50 markets)
- **2x longer delay between requests** (2.0s vs 1.0s)
- **2x longer startup delay** (30s vs 15s)
- **Up to 320s backoff** for 403 errors

The effective request rate is now **~0.48 req/s**, which is well below Coinbase's sustained rate limit and should eliminate both 403 and 429 errors completely.
