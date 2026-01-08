# Quick Reference: Rate Limit Fix (Jan 2026)

## What Changed?

### Before (Rate Limited ❌)
- Scanned **730 markets** every 2.5 minutes
- No caching → 730 API calls per cycle
- Delay: 0.25s between requests (4 req/s)
- Result: **429 Too Many Requests errors**

### After (Optimized ✅)
- Scans **100 markets** per cycle (rotates through all 730)
- Caching reduces duplicate requests
- Delay: 0.5s between requests (2 req/s)
- Result: **No rate limiting, reliable trading**

## Key Numbers

| Metric | Before | After | Impact |
|--------|--------|-------|--------|
| Markets/cycle | 730 | 100 | -86% API calls |
| Scan delay | 0.25s | 0.5s | 50% slower rate |
| Full coverage | 2.5 min | 20 min | Still acceptable |
| Rate limit errors | Frequent | None | ✅ Fixed |

## How It Works

### Market Rotation
Cycle 1: Markets 0-99  
Cycle 2: Markets 100-199  
Cycle 3: Markets 200-299  
...  
Cycle 8: Markets 700-729, wrap to 0-30

**Result**: Every market scanned within 20 minutes instead of 2.5 minutes.

### Caching
- **Candle data**: Cached for 150 seconds (one cycle)
- **Market list**: Cached for 1 hour
- **Effect**: No duplicate API calls for same data

### Adaptive Backoff
If rate limited:
1. First retry: Wait 1.5s + jitter
2. Second retry: Wait 3s + jitter
3. Third retry: Wait 6s + jitter
4. After 3 consecutive failures: Pause 3s for API recovery

## Monitoring

### Good Logs (Expected)
```
📊 Market rotation: scanning batch 0-100 of 730 (0% through cycle)
✅ Using cached market list (730 markets, age: 45s)
```

### Bad Logs (Should Not See)
```
429 Client Error: Too Many Requests
⚠️ Rate limited: 5 times
```

## Configuration

Edit `/bot/trading_strategy.py`:

```python
# Adjust batch size (50-200 recommended)
MARKET_BATCH_SIZE = 100

# Disable rotation (not recommended)
MARKET_ROTATION_ENABLED = False

# Adjust scan delay (0.3-1.0s recommended)
MARKET_SCAN_DELAY = 0.5
```

## Troubleshooting

### Still seeing 429 errors?
1. Increase `MARKET_SCAN_DELAY` to 1.0s
2. Reduce `MARKET_BATCH_SIZE` to 50
3. Check if multiple bot instances are running

### Missing trading opportunities?
1. Increase `MARKET_BATCH_SIZE` to 150
2. Check logs for "signals_found" count
3. Verify strategy filters aren't too strict

## Files Modified
- `bot/trading_strategy.py` - Main fixes
- `bot/broker_manager.py` - Enhanced retry logic
- `RATE_LIMIT_FIX_JAN_2026.md` - Full documentation
- `RATE_LIMIT_QUICK_REF.md` - This file

## Testing
```bash
# Check constants loaded
python -c "from bot.trading_strategy import MARKET_SCAN_DELAY; print(MARKET_SCAN_DELAY)"

# Should output: 0.5

# Run bot and watch for rotation logs
./start.sh
```

## Support
See `RATE_LIMIT_FIX_JAN_2026.md` for detailed implementation notes.
