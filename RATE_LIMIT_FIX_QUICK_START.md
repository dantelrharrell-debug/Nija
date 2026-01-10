# QUICK START: 403 Rate Limiting Fix (Jan 10, 2026)

## What Was Fixed

The bot was getting **403 "Forbidden Too many errors"** from Coinbase because it was making too many API requests too quickly. The API key was being temporarily blocked.

## What Changed

### 1. Longer Wait Times for 403 Errors
- **Before**: 30-45 seconds
- **After**: 60-90 seconds
- **Why**: Gives Coinbase API enough time to unblock the key

### 2. Slower Bot Startup
- **Before**: Trading starts immediately
- **After**: Waits 30-60 seconds before first trade
- **Why**: Prevents API calls during setup from conflicting with trading

### 3. Staggered Broker Starts
- **Before**: All brokers start at once
- **After**: 10-second delay between each broker
- **Why**: Spreads out API requests

### 4. Smarter Error Handling
- **403 errors** (API key blocked): Long 60-90s delay
- **429 errors** (rate limit): Exponential backoff (5s, 10s, 20s...)
- **Network errors**: Moderate backoff (10s, 20s, 40s...)
- **Why**: Different problems need different solutions

## What to Expect

### When Bot Starts
```
T=0s:     Bot connects to Coinbase
T=10s:    Second broker starts (if you have one)
T=30-60s: First broker begins trading
T=40-70s: Second broker begins trading
```

### In the Logs
You should see messages like:
```
⏳ coinbase: Waiting 47.2s before first cycle (prevents rate limiting)...
⏳ Staggering start: waiting 10s before starting alpaca...
```

### If 403 Error Occurs
```
⚠️  Connection attempt 1/10 failed (retryable): 403 Client Error
   API key temporarily blocked - waiting 67.3s before retry...
🔄 Retrying connection in 67.3s...
✅ Connected to Coinbase (succeeded on attempt 2)
```

## Is It Working?

### Good Signs ✅
- Bot waits 30-60 seconds before trading
- No repeated 403 errors
- Smooth operation after startup
- Successful retries after 403 errors

### Bad Signs ❌
- Still getting 403 errors every minute
- Bot starts trading immediately (no delay)
- Multiple 403 errors in a row with short delays

## Trade-offs

**Pro:**
- ✅ No more API key blocks
- ✅ Stable long-term operation
- ✅ Better for Coinbase API health

**Con:**
- ⚠️ Slower startup (60-90 seconds vs immediate)
- ⚠️ May miss very early market moves
- ⚠️ Takes longer to recover from errors

**Bottom Line:** Slower and more stable is better than fast and broken.

## What If It Still Fails?

If you still see 403 errors after this fix:

1. **Check if delays are applied**: Look for "Waiting...s before first cycle" in logs
2. **Wait longer**: The first 2-3 minutes after startup are most critical
3. **Reduce trading pairs**: Lower `MARKET_SCAN_LIMIT` in `trading_strategy.py`
4. **Increase delays further**: Modify `FORBIDDEN_BASE_DELAY` in `broker_manager.py`

## Files Changed

1. **bot/broker_manager.py** - Rate limiting constants
2. **bot/independent_broker_trader.py** - Startup delays

## Deployment

These changes are ready to deploy. No configuration changes needed.

Just push to production and watch the logs for the new delay messages.

---

**Fix Date:** January 10, 2026  
**Issue:** 403 "Forbidden Too many errors"  
**Status:** ✅ Complete and validated
