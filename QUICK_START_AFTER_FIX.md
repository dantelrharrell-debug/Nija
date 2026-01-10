# Quick Start: After 403 Rate Limit Fix

## What Changed?

### 🎯 Main Fix: Adaptive Batch Sizing
```
BEFORE: Always scan 15 markets per cycle
AFTER:  Start with 5, grow to 15 based on API health
```

### ⏱️ Timing Changes
```
Market scan delay:    6.5s → 8.0s
403 retry delay:      20-30s → 30-45s
Circuit breaker:      15-20s → 20-30s
Post-startup delay:   0s → 10s
```

### 📊 Rate Limits
```
get_candles:         10 req/min → 8 req/min (7.5s interval)
get_all_products:    6 req/min → 5 req/min (12s interval)
```

## How to Monitor

### Check Logs for Warmup
```bash
# Should see these messages in first 10 minutes:
🔥 Warmup mode: cycle 1/3, batch size=5
🔥 Warmup mode: cycle 2/3, batch size=5
🔥 Warmup mode: cycle 3/3, batch size=5
📊 API health moderate (85%), batch size=15  # After warmup
```

### Check for Errors
```bash
# Should NOT see:
403 Client Error: Forbidden Too many errors
⚠️ API key temporarily blocked

# OK to see occasionally (circuit breaker working):
🛑 CIRCUIT BREAKER: Pausing for 20s
⚠️ API health low (45%), using reduced batch size=5
```

## What to Expect

### Timeline After Deploy
| Time | Event |
|------|-------|
| 0:00 | Bot starts |
| 0:45 | Connect to Coinbase (after 45s delay) |
| 0:55 | Fetch 351 product list |
| 1:05 | **10s cooldown** ⭐ |
| 1:05 | Cycle 1: Scan 5 markets (40s) |
| 3:35 | Cycle 2: Scan 5 markets (40s) |
| 6:05 | Cycle 3: Scan 5 markets (40s) |
| 8:35 | Cycle 4: Scan 10-15 markets (80-120s) |

### Normal Operation
- ✅ Scanning 5-15 markets per cycle
- ✅ 8 second delay between markets
- ✅ API health score > 80%
- ✅ No 403 errors
- ✅ Trading normally

### Degraded Operation
- ⚠️ Scanning only 5 markets (health < 50%)
- ⚠️ Circuit breakers activating
- ⚠️ Longer delays between markets
- ⚠️ Fewer trading opportunities
- ⚠️ Still functional, just slower

## Key Indicators

### ✅ GOOD
```
✅ Rate limiter initialized (12 req/min default, 8 req/min for candles)
✅ Position cap OK (0/8) - entries enabled
💰 Trading balance: $10.05
📊 API health moderate (85%), batch size=15
```

### ⚠️ WARNING
```
⚠️ Possible rate limiting detected (2 consecutive failures)
🛑 CIRCUIT BREAKER: Pausing for 20s to allow API to recover...
⚠️ API health low (45%), using reduced batch size=5
```

### 🚨 ERROR
```
🚨 GLOBAL CIRCUIT BREAKER: 4 total errors - stopping scan
403 Client Error: Forbidden Too many errors
⚠️ API key temporarily blocked (403)
```

## If You Still See 403 Errors

### Step 1: Check Startup Logs
Look for these confirmations:
- [x] "Rate limiter initialized (12 req/min default, 8 req/min for candles)"
- [x] "Cooling down for 10s after bulk product fetch"
- [x] "Warmup mode: cycle 1/3, batch size=5"

### Step 2: Verify Delays
```bash
# Time between "Scanning X markets" messages should be:
# - First 3 cycles: ~2.5 minutes apart
# - Later cycles: ~2.5-3 minutes apart
```

### Step 3: Check API Key
```bash
# Verify API key is valid and has correct permissions
echo $COINBASE_API_KEY | wc -c  # Should be ~95 chars
```

### Step 4: Escalate
If 403 errors persist after warmup (first 10 minutes):
1. Increase delays even more (10s → 12s scan delay)
2. Reduce batch size max (15 → 10 markets)
3. Add longer startup delay (45s → 60s)
4. Contact Coinbase support re: rate limits

## Quick Commands

### Watch Live Logs
```bash
railway logs --follow
```

### Count Errors
```bash
railway logs | grep "403" | wc -l
```

### Check Health Score
```bash
railway logs | grep "API health"
```

### Check Batch Size
```bash
railway logs | grep "batch size"
```

## Success = No Action Needed

If logs show:
- ✅ Warmup completing (3 cycles)
- ✅ Health score > 80%
- ✅ Batch size growing to 15
- ✅ No 403 errors

**Then the fix is working!** No intervention needed. Bot will automatically:
- Scale up when API is healthy
- Scale down when API is stressed
- Recover from transient errors
- Prevent rate limit bans

---
**Ready for Production** ✅
