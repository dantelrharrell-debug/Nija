# Rate Limiting Fix for Coinbase API (403 Forbidden Errors)

## Problem Statement

The NIJA bot was experiencing frequent 403 "Forbidden - Too many errors" responses from the Coinbase API, preventing it from scanning markets and executing trades. The errors appeared as:

```
2026-01-10T01:14:43 - coinbase.RESTClient - ERROR - HTTP Error: 403 Client Error: Forbidden Too many errors
WARNING:root:⚠️  API key temporarily blocked (403) on ALT-USD, waiting 16.8s before retry 2/3
```

## Root Cause Analysis

1. **Uncontrolled Bulk API Call**: The `get_all_products()` method in `broker_manager.py` was calling `client.get_products(get_all_products=True)` without any rate limiting.

2. **Massive Data Volume**: This single call fetches 12,333+ cryptocurrency markets from Coinbase, likely making multiple paginated API requests in rapid succession.

3. **SDK Internal Pagination**: The Coinbase SDK's `get_all_products=True` parameter internally handles pagination, but makes these requests quickly without delays between pages.

4. **Rate Limit Exhaustion**: These rapid requests would exhaust Coinbase's rate limits (approximately 10 req/s burst, but much lower sustained rate) before the bot even began market scanning.

5. **Cascade Effect**: Once rate-limited on the product list fetch, subsequent candle fetching and position management calls would also fail with 403 errors.

## Solution Implemented

### 1. Rate Limiter Integration

Added rate-limited wrapper around the `get_products()` call:

```python
def _fetch_products():
    """Inner function for rate-limited product fetching"""
    return self.client.get_products(get_all_products=True)

if self._rate_limiter:
    # Rate-limited call - enforces minimum interval between requests
    products_resp = self._rate_limiter.call('get_all_products', _fetch_products)
else:
    # Fallback to direct call without rate limiting
    products_resp = _fetch_products()
```

### 2. Ultra-Conservative Rate Limits

Configured extremely conservative rate limits specifically for bulk operations:

- **get_all_products**: 6 requests/minute (10 seconds between calls)
- **get_candles**: 10 requests/minute (6 seconds between calls)
- **Default**: 12 requests/minute (5 seconds between calls)

The 10-second interval for `get_all_products` ensures the Coinbase API has ample time to recover between large bulk requests.

### 3. Retry Logic with Exponential Backoff

Implemented intelligent retry logic that handles both 403 and 429 errors:

```python
while retry_count <= max_retries:
    try:
        # Attempt to fetch products
        products_resp = self._rate_limiter.call('get_all_products', _fetch_products)
        break  # Success!
        
    except Exception as fetch_err:
        error_str = str(fetch_err)
        
        # Check if it's a rate limit error (403 or 429)
        is_rate_limit = '429' in error_str or 'rate limit' in error_str.lower()
        is_forbidden = '403' in error_str or 'forbidden' in error_str.lower() or 'too many' in error_str.lower()
        
        if (is_rate_limit or is_forbidden) and retry_count < max_retries:
            retry_count += 1
            
            # Calculate backoff delay
            if is_forbidden:
                # 403 errors: Fixed delay with jitter (15-20s)
                delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
            else:
                # 429 errors: Exponential backoff (5s, 10s, 20s)
                delay = RATE_LIMIT_BASE_DELAY * (2 ** (retry_count - 1))
            
            time.sleep(delay)
            continue
        else:
            # Not a rate limit error or max retries reached
            raise fetch_err
```

**Retry Strategy:**
- **403 Forbidden errors**: Fixed 15-20 second delay with random jitter
  - Indicates API key is temporarily blocked
  - Requires longer wait time for API to unblock the key
  
- **429 Rate Limit errors**: Exponential backoff (5s → 10s → 20s)
  - Indicates temporary rate limit reached
  - Progressively longer delays give API time to reset limits

- **Max Retries**: 3 attempts before falling back to FALLBACK_MARKETS

### 4. Fallback Mechanism

If all retries are exhausted, the bot falls back to a curated list of 50 popular cryptocurrency markets:

```python
FALLBACK_MARKETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD',
    # ... 45 more popular pairs
]
```

This ensures the bot can continue trading even if the full product list is unavailable.

### 5. Existing Cache Optimization

The solution leverages existing market list caching in `trading_strategy.py`:

- **Cache TTL**: 3600 seconds (1 hour)
- **Cache Logic**: Only calls `get_all_products()` once per hour
- **Cache Age Logging**: Shows cache age to help debug refresh issues

## Technical Details

### Rate Limiter Implementation

The `RateLimiter` class (in `bot/rate_limiter.py`) enforces minimum intervals between API calls:

```python
class RateLimiter:
    def __init__(self, default_per_min: int = 12, per_key_overrides: Optional[Dict[str, int]] = None):
        self.default_per_min = int(default_per_min) if default_per_min > 0 else 12
        self.per_key_overrides = per_key_overrides or {}
        self._last_called: Dict[str, float] = {}
        self._locks: Dict[str, Lock] = {}
    
    def call(self, key: str, fn: Callable[[], Any]) -> Any:
        """
        Execute fn() while enforcing inter-call delay for `key`.
        This blocks the current thread until the request may proceed.
        """
        lock = self._get_lock(key)
        with lock:
            now = time.time()
            last = self._last_called.get(key, 0)
            interval = self._get_interval(key)
            delta = now - last
            if delta < interval:
                to_sleep = interval - delta
                jitter = min(0.2, to_sleep * 0.1)
                time.sleep(to_sleep + jitter)
            result = fn()
            self._last_called[key] = time.time()
            return result
```

### Constants Used

```python
# From broker_manager.py
RATE_LIMIT_MAX_RETRIES = 3  # Maximum retries for rate limit errors
RATE_LIMIT_BASE_DELAY = 5.0  # Base delay for exponential backoff (429 errors)
FORBIDDEN_BASE_DELAY = 15.0  # Fixed delay for 403 errors (API key ban)
FORBIDDEN_JITTER_MAX = 5.0   # Maximum random jitter for 403 delays (15-20s total)
```

## Testing Results

Created comprehensive test suite (`/tmp/test_rate_limiting.py`) that validates:

1. **Rate Limiter Initialization**: ✅ PASS
   - Rate limiter properly initialized
   - Correct configuration for all endpoints
   - get_all_products correctly set to 6 req/min

2. **Retry Logic for 403 Errors**: ✅ PASS
   - Correctly retries on 403 errors
   - Applies appropriate delays (15-20s with jitter)
   - Successfully fetches products after retries
   - Falls back if max retries exceeded

3. **Rate Limiter Call Spacing**: ✅ PASS
   - First call is immediate (no delay)
   - Subsequent calls enforce 10s interval
   - Consistent enforcement across multiple calls

**All tests passed: 3/3** 🎉

## Expected Behavior After Fix

### Before Fix
```
2026-01-10T01:14:43 | INFO | 🔄 coinbase - Cycle #35
2026-01-10T01:14:43 | INFO | 💰 Fetching account balance...
ERROR: 403 Client Error: Forbidden Too many errors
ERROR: 403 Client Error: Forbidden Too many errors
ERROR: 403 Client Error: Forbidden Too many errors
[Bot unable to scan markets or execute trades]
```

### After Fix
```
2026-01-10T01:14:43 | INFO | 🔄 coinbase - Cycle #35
2026-01-10T01:14:43 | INFO | 📡 Fetching all products from Coinbase API (700+ markets)...
2026-01-10T01:14:43 | INFO | ✅ Rate limiter initialized (12 req/min default, 6 req/min for get_all_products)
2026-01-10T01:14:43 | INFO | ✅ Successfully fetched 730 USD/USDC trading pairs from Coinbase API
2026-01-10T01:14:43 | INFO | ✅ Using cached market list (730 markets, age: 45s)
2026-01-10T01:14:43 | INFO | 🔍 Scanning for new opportunities...
[Bot successfully scans markets and executes trades]
```

### If Rate Limit Hit (Retry Scenario)
```
2026-01-10T01:14:43 | INFO | 📡 Fetching all products from Coinbase API (700+ markets)...
WARNING: ⚠️  API key temporarily blocked (403) on get_all_products, waiting 17.3s before retry 1/3
[Waits 17.3 seconds]
WARNING: ⚠️  API key temporarily blocked (403) on get_all_products, waiting 18.9s before retry 2/3
[Waits 18.9 seconds]
2026-01-10T01:14:43 | INFO | ✅ Successfully fetched 730 USD/USDC trading pairs from Coinbase API
[Continues normally]
```

### If All Retries Exhausted (Fallback Scenario)
```
2026-01-10T01:14:43 | INFO | 📡 Fetching all products from Coinbase API (700+ markets)...
WARNING: ⚠️  API key temporarily blocked (403) on get_all_products, waiting 17.3s before retry 1/3
WARNING: ⚠️  API key temporarily blocked (403) on get_all_products, waiting 18.9s before retry 2/3
WARNING: ⚠️  API key temporarily blocked (403) on get_all_products, waiting 16.5s before retry 3/3
ERROR: ⚠️  Failed to fetch products after retries
WARNING: ⚠️  Could not fetch products from API, using fallback list of popular markets
INFO: Using 50 fallback markets
[Continues trading with 50 popular pairs]
```

## Impact on Bot Performance

### API Call Reduction
- **Before**: Unlimited, rapid fire requests
- **After**: Maximum 6 product list calls per minute (realistically 1 per hour due to caching)
- **Candle Fetching**: Maximum 10 calls per minute with 6s spacing
- **Other Calls**: Maximum 12 calls per minute with 5s spacing

### Market Scanning
- **Market List Refresh**: Once per hour (cached)
- **Market Batch Size**: 25 markets per cycle (unchanged)
- **Scan Interval**: 4 seconds between markets (unchanged)
- **Full Rotation**: ~29 cycles to scan all 730 markets (~72 minutes)

### Recovery Time
- **403 Error Recovery**: 15-20 seconds per retry attempt
- **429 Error Recovery**: 5-20 seconds (exponential backoff)
- **Max Recovery Time**: ~60 seconds (3 retries × 20s max delay)

## Deployment Considerations

### No Configuration Changes Required
- All rate limiting is automatic
- No environment variables to set
- No manual intervention needed

### Backward Compatibility
- Falls back to direct calls if RateLimiter unavailable
- Falls back to FALLBACK_MARKETS if API fails
- Existing caching behavior preserved

### Monitoring
Watch logs for:
- Rate limit warnings: `⚠️  API key temporarily blocked (403)`
- Fallback activation: `⚠️  Could not fetch products from API, using fallback list`
- Cache hits: `✅ Using cached market list (730 markets, age: XXXs)`

### Success Indicators
- No 403 errors in logs
- Market list fetched successfully every hour
- Consistent market scanning without interruption
- Normal trading operations resume

## Related Files Modified

1. **bot/broker_manager.py** (Primary changes)
   - Modified `get_all_products()` method
   - Added rate limiting wrapper
   - Added retry logic with backoff
   - Updated rate limiter initialization

2. **bot/rate_limiter.py** (No changes - existing code)
   - RateLimiter class used for enforcement
   - TTLCache used for response caching

3. **bot/trading_strategy.py** (No changes - existing code)
   - Market list caching already implemented
   - Cache TTL already set to 3600s

## Future Improvements

1. **Dynamic Rate Limiting**: Adjust rate limits based on API response headers
2. **Circuit Breaker Pattern**: Temporarily disable product fetching after repeated failures
3. **Metric Collection**: Track API call patterns and rate limit hits
4. **Alert System**: Notify operators when fallback markets are used

## Conclusion

This fix addresses the root cause of 403 Forbidden errors by:
1. Implementing proper rate limiting for bulk API calls
2. Adding intelligent retry logic with exponential backoff
3. Providing fallback mechanisms for graceful degradation
4. Maintaining existing caching optimizations

The bot should now operate reliably without hitting Coinbase API rate limits, enabling consistent market scanning and trade execution.
