# Rate Limiting Fix - January 2026

## Problem Summary
NIJA trading bot was experiencing **429 Too Many Requests** errors from the Coinbase Advanced Trade API during market scanning, preventing the bot from trading effectively.

## Root Causes

### 1. Excessive Market Scanning
- **Before**: Scanned all 730+ cryptocurrency markets every 2.5-minute cycle
- **Result**: 730+ `get_candles()` API calls per cycle
- **Issue**: Coinbase rate limit is ~10 req/s burst, ~3-5 req/s sustained
- **Impact**: Even with 0.25s delays, sustained rate was too high

### 2. No Request Caching
- Every cycle made fresh API calls for the same candle data
- Market list was fetched on every cycle
- No deduplication of requests within a cycle

### 3. Insufficient Delays
- `MARKET_SCAN_DELAY = 0.25s` → 4 requests/second
- Startup delay of 10s was insufficient after rate limiting
- No adaptive backoff when rate limited

### 4. Position Fetching Issues
- `get_positions()` called multiple times per cycle
- Each call could trigger additional API requests

## Solutions Implemented

### 1. Market Rotation System ⭐ (Primary Fix)

Instead of scanning all 730 markets every cycle, we now:
- Scan only **100 markets per cycle**
- Rotate through different market batches each cycle
- Complete full rotation in ~8 cycles (20 minutes)

**Benefits:**
- Reduces API calls by **86%** per cycle (730 → 100)
- Still covers all markets within reasonable timeframe
- Distributes API load across time

**Implementation:**
```python
# New constants
MARKET_BATCH_SIZE = 100
MARKET_ROTATION_ENABLED = True

# Instance variables
self.market_rotation_offset = 0  # Tracks next batch
self.all_markets_cache = []      # Cached market list
```

### 2. Request Caching

**Candle Data Cache:**
- TTL: 150 seconds (one trading cycle)
- Cache key: `{symbol}_{timeframe}_{count}`
- Prevents duplicate requests for same market data

**Market List Cache:**
- TTL: 3600 seconds (1 hour)
- Prevents fetching product list on every cycle
- Refreshes hourly to stay current

**Implementation:**
```python
def _get_cached_candles(self, symbol: str, timeframe: str = '5m', count: int = 100):
    cache_key = f"{symbol}_{timeframe}_{count}"
    current_time = time.time()
    
    # Check cache first
    if cache_key in self.candle_cache:
        cached_time, cached_data = self.candle_cache[cache_key]
        if current_time - cached_time < self.CANDLE_CACHE_TTL:
            return cached_data  # Cache hit!
    
    # Cache miss - fetch fresh data
    candles = self.broker.get_candles(symbol, timeframe, count)
    self.candle_cache[cache_key] = (current_time, candles)
    return candles
```

### 3. Increased Rate Limit Delays

| Constant | Before | After | Max Rate |
|----------|--------|-------|----------|
| `MARKET_SCAN_DELAY` | 0.25s | **0.5s** | 2 req/s |
| `POSITION_CHECK_DELAY` | 0.2s | **0.3s** | 3.3 req/s |
| `SELL_ORDER_DELAY` | 0.3s | **0.5s** | 2 req/s |
| Startup delay | 10s | **15s** | N/A |

### 4. Enhanced Exponential Backoff

**Before:**
- Base delay: 1.0s
- Jitter: 30%
- Max delay: ~4s after 3 retries

**After:**
- Base delay: **1.5s**
- Jitter: **50%**
- Max delay: ~9s after 3 retries
- Better prevents thundering herd

### 5. Adaptive Rate Limit Detection

Monitors consecutive failures and adds recovery pauses:
```python
if rate_limit_counter >= 3:
    logger.warning("⏸️  Pausing for 3s to allow API rate limits to reset...")
    time.sleep(3.0)
    rate_limit_counter = 0
```

## Performance Impact

### API Request Reduction

**Per Cycle (2.5 minutes):**
- Before: ~730 candle requests + position checks + orders
- After: ~100 candle requests (87% reduction) + position checks + orders

**Scan Time:**
- Before: ~183 seconds (730 markets × 0.25s)
- After: ~50 seconds (100 markets × 0.5s)

### Market Coverage

**Single Cycle:**
- Before: 100% of markets (730/730)
- After: 13.7% of markets (100/730)

**Full Rotation:**
- Before: 1 cycle (2.5 minutes)
- After: ~8 cycles (20 minutes)

**Trade-off Analysis:**
- ✅ PRO: Prevents rate limiting, allows bot to run reliably
- ✅ PRO: Still finds opportunities across all markets within 20 minutes
- ✅ PRO: More sustainable API usage pattern
- ⚠️ CON: Individual market checked less frequently (every 20 min vs 2.5 min)
- ✅ MITIGATION: Most opportunities persist for >20 minutes in crypto markets

## Configuration Variables

All configurable in `/bot/trading_strategy.py`:

```python
# Market scanning
MARKET_SCAN_LIMIT = 100         # Markets to scan per cycle
MARKET_BATCH_SIZE = 100         # Batch size for rotation
MARKET_ROTATION_ENABLED = True  # Enable/disable rotation

# Rate limiting delays (seconds)
POSITION_CHECK_DELAY = 0.3
SELL_ORDER_DELAY = 0.5
MARKET_SCAN_DELAY = 0.5

# Cache TTLs (seconds)
self.CANDLE_CACHE_TTL = 150     # 2.5 minutes
self.MARKETS_CACHE_TTL = 3600   # 1 hour
```

## Monitoring

### Log Messages to Watch

**✅ Good:**
```
📊 Market rotation: scanning batch 0-100 of 730 (0% through cycle)
✅ Using cached market list (730 markets, age: 45s)
BTC-USD: Using cached candles (age: 32s)
```

**⚠️ Warning:**
```
⚠️ Possible rate limiting detected (5 consecutive failures)
⏸️  Pausing for 3s to allow API rate limits to reset...
Rate limited on ETH-USD, retrying in 2.3s (attempt 1/3)
```

**❌ Error (should be rare now):**
```
429 Client Error: Too Many Requests
```

### Metrics to Track

1. **Rate Limit Occurrences**: Should be near zero
2. **Cache Hit Rate**: Check log for "Using cached" messages
3. **Scan Completion Time**: Should be ~50 seconds per cycle
4. **Market Rotation Progress**: Should cycle through all markets in ~20 minutes

## Testing Checklist

- [x] Python syntax validation
- [ ] Local startup test
- [ ] Monitor first 3 cycles for rate limits
- [ ] Verify market rotation in logs
- [ ] Check cache hit rates
- [ ] Confirm no 429 errors in production
- [ ] Verify trading still executes successfully

## Rollback Plan

If issues occur, revert by changing these values:

```python
# Quick rollback to previous behavior (not recommended)
MARKET_SCAN_LIMIT = 730           # Scan all markets (may cause rate limits)
MARKET_ROTATION_ENABLED = False   # Disable rotation
MARKET_SCAN_DELAY = 0.25          # Faster scanning (risky)
```

**Better approach**: Adjust batch size instead:
```python
MARKET_BATCH_SIZE = 150  # Scan more markets per cycle
```

## Future Improvements

1. **Dynamic Batch Sizing**: Adjust batch size based on API response times
2. **Priority Markets**: Always scan high-volume markets, rotate low-volume
3. **Smart Caching**: Invalidate cache on significant price movements
4. **Rate Limit Telemetry**: Track 429 errors to optimize delays further
5. **Parallel Requests**: Use connection pooling for better throughput (risky)

## References

- Coinbase Advanced Trade API docs: https://docs.cloud.coinbase.com/advanced-trade-api/docs/
- Rate limiting best practices: exponential backoff, jitter, circuit breakers
- Previous rate limit fixes: `RATE_LIMIT_FIX_IMPLEMENTATION.md`, `RATE_LIMITING_FIX.md`

## Author

AI-assisted fix by GitHub Copilot - January 2026
Issue reported: CI/Build failure with 429 errors from Coinbase API
