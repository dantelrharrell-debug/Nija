# Quick Reference: Monitoring Rate Limit Fix

## What to Watch in the Logs

### ✅ Good Signs (Fix Working)

```
🔥 Warmup mode: cycle 1/3, batch size=5
📊 Market rotation: scanning batch 0-5 of 351 (1% through cycle)
Scanning 5 markets (batch rotation mode)...
✅ Under cap (no action needed)
```

### ⚠️ Warning Signs (Temporary Issues)

```
⚠️ Possible rate limiting detected (2 consecutive failures)
🛑 CIRCUIT BREAKER: Pausing for 20s to allow API to recover...
⚠️ API health low (45%), using reduced batch size=5
```

### 🚨 Problem Signs (Fix Not Working)

```
403 Client Error: Forbidden Too many errors
⚠️ API key temporarily blocked (403) on 1INCH-USD
🚨 GLOBAL CIRCUIT BREAKER: 4 total errors - stopping scan
```

## Expected Timeline After Deploy

### First 10 Minutes (Cycles 1-3)
- **00:00** - Bot starts, 45s delay
- **00:45** - Connect to Coinbase
- **00:55** - Fetch 351 products
- **01:05** - **10s cooldown** ⭐ NEW
- **01:05** - Cycle 1: Scan 5 markets (40s)
- **03:35** - Cycle 2: Scan 5 markets (40s)
- **06:05** - Cycle 3: Scan 5 markets (40s)

### After 10 Minutes (Cycle 4+)
- **08:35** - Cycle 4: Scan 10-15 markets (80-120s) if health > 80%
- **11:05+** - Normal operation, batch size based on API health

## Key Metrics to Track

### API Health Score
- **100%** - Perfect (initial state)
- **80-100%** - Excellent (full batch size = 15)
- **50-79%** - Moderate (mid batch size = 10)
- **0-49%** - Degraded (min batch size = 5)

### Batch Size Progression
- Cycle 1-3: **5 markets** (warmup)
- Cycle 4+: **5-15 markets** (based on health)

### Delays Between Markets
- **8 seconds** between each market scan
- **20 seconds** on circuit breaker activation
- **30 seconds** on global circuit breaker
- **30-45 seconds** on 403 error retry

## Log Commands

### Watch live logs (Railway)
```bash
railway logs --follow
```

### Search for specific issues
```bash
# Check for 403 errors
railway logs | grep "403"

# Check warmup progress
railway logs | grep "Warmup mode"

# Check API health
railway logs | grep "API health"

# Check batch sizes
railway logs | grep "batch size"
```

## Quick Health Check

Run this in logs to see if fix is working:

```bash
# Should see warmup messages in first 3 cycles
grep "Warmup mode: cycle" logs.txt

# Should NOT see 403 errors after startup
grep "403" logs.txt | wc -l  # Should be 0 or very low

# Should see API health staying high
grep "API health" logs.txt | tail -20
```

## If 403 Errors Still Occur

### Immediate Actions
1. Check if API key is valid: `echo $COINBASE_API_KEY | wc -c`
2. Verify rate limiter is active: Look for "Rate limiter initialized"
3. Check cooldown is running: Look for "Cooling down for 10s"

### Escalation Steps
1. Increase `MARKET_SCAN_DELAY` to 10.0s
2. Reduce `MARKET_BATCH_SIZE_MAX` to 10
3. Increase `FORBIDDEN_BASE_DELAY` to 45.0s
4. Add longer startup delay (60s instead of 45s)

### Nuclear Option
```python
# In bot/trading_strategy.py
MARKET_BATCH_SIZE_MIN = 3  # Ultra conservative
MARKET_BATCH_SIZE_MAX = 5  # Very slow but safe
MARKET_SCAN_DELAY = 12.0   # 12 seconds between markets
```

## Success Criteria

After 30 minutes of operation:
- [ ] No 403 errors in logs
- [ ] API health score > 80%
- [ ] Batch size increased from 5 to 10-15
- [ ] Bot scanning markets successfully
- [ ] No circuit breaker activations after warmup

## Rollback Command

If needed:
```bash
git revert 9be4967 3963ab7
git push origin copilot/fix-position-size-redeploy
```

## Contact

If issues persist, provide:
1. Full startup logs (first 10 minutes)
2. API health score progression
3. Any 403 error messages
4. Batch size progression over time
