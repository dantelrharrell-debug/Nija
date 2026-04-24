# Kraken Rate Limiting Profiles

## Overview

NIJA now features intelligent rate limiting profiles for Kraken API calls, optimized for different account sizes and trading styles. The system automatically separates entry/exit operations from monitoring operations to maximize trading efficiency while minimizing API overhead.

## Key Features

### ✅ Separate Entry/Exit vs Monitoring Budgets

Kraken's API has a unique cost structure where **AddOrder calls are FREE** (0 API points), but **Balance checks cost 1 point**. The new rate profiles take advantage of this by:

- **Entry Operations (Buy)**: Minimal rate limiting (2-3s intervals) - FREE on Kraken
- **Exit Operations (Sell)**: Minimal rate limiting (2-3s intervals) - FREE on Kraken
- **Monitoring Operations (Balance)**: Conservative rate limiting (10-30s intervals) - Saves API budget
- **Query Operations (Order Status)**: Moderate rate limiting (5-15s intervals) - Controlled usage

### ✅ Auto-Selection Based on Account Size

The system automatically selects the optimal rate profile based on your account balance:

| Balance Range | Profile | Entry Interval | Monitoring Interval |
|--------------|---------|----------------|---------------------|
| $20 - $100 | **LOW_CAPITAL** | 3 seconds | 30 seconds |
| $100 - $1,000 | **STANDARD** | 2 seconds | 10 seconds |
| $1,000+ | **AGGRESSIVE** | 1 second | 5 seconds |

### ✅ Kraken-Safe Low-Capital Mode

For small accounts ($20-$100), the **LOW_CAPITAL** profile minimizes API overhead:

- **30-second intervals** between balance checks (vs 10s in standard)
- **Balance caching** enabled with 60-second TTL
- **20% API budget** allocated to monitoring (vs 40% in standard)
- **80% API budget** reserved for queries and order management

This ensures small accounts aren't "wasting" API calls on frequent monitoring when capital efficiency matters more.

## How It Works

### 1. Automatic Profile Selection

When your Kraken broker connects, it automatically:

1. Fetches your account balance
2. Selects the appropriate rate profile
3. Logs the selected profile and intervals

```python
# Example log output during connection:
✅ KRAKEN PRO CONNECTED (MASTER)
   Account: MASTER
   USD Balance: $150.00
   USDT Balance: $0.00
   Total: $150.00
   📊 Rate Profile: Standard Rate Profile
      Entry: 2.0s interval
      Monitoring: 10.0s interval
```

### 2. Per-Category Rate Limiting

Each API call is categorized and rate-limited independently:

```python
# Entry operation (buy order)
api_category = KrakenAPICategory.ENTRY
result = self._kraken_private_call('AddOrder', params, category=api_category)
# → Uses 2s interval (STANDARD mode)

# Monitoring operation (balance check)
api_category = KrakenAPICategory.MONITORING
balance = self._kraken_private_call('Balance', category=api_category)
# → Uses 10s interval (STANDARD mode)
```

### 3. API Budget Management

Kraken Tier 0 accounts have a **15 points/minute** budget. The profiles allocate this budget intelligently:

**STANDARD Profile:**
- Total Budget: 15 points/minute
- Reserve: 3 points (safety buffer)
- Monitoring: 40% (6 points/min max)
- Queries: 60% (9 points/min max)

**LOW_CAPITAL Profile:**
- Total Budget: 15 points/minute
- Reserve: 5 points (larger safety buffer)
- Monitoring: 20% (3 points/min max)
- Queries: 80% (12 points/min max)

## API Categories

The system recognizes four categories of API operations:

### 1. ENTRY (Buy Orders)
- **API Method**: `AddOrder` with `type='buy'`
- **Cost**: 0 points (FREE on Kraken)
- **Rate Limit**: 1-3 seconds (depends on profile)
- **Use Case**: Opening new positions

### 2. EXIT (Sell Orders)
- **API Method**: `AddOrder` with `type='sell'`
- **Cost**: 0 points (FREE on Kraken)
- **Rate Limit**: 1-3 seconds (depends on profile)
- **Use Case**: Closing positions, taking profit, stop losses

### 3. MONITORING (Balance Checks)
- **API Methods**: `Balance`, `TradeBalance`
- **Cost**: 1 point per call
- **Rate Limit**: 5-30 seconds (depends on profile)
- **Use Case**: Checking available funds, portfolio value

### 4. QUERY (Order Status)
- **API Methods**: `QueryOrders`, `OpenOrders`, `ClosedOrders`
- **Cost**: 1-2 points per call
- **Rate Limit**: 3-15 seconds (depends on profile)
- **Use Case**: Checking order status, trade history

## Configuration Profiles

### LOW_CAPITAL Mode ($20-$100)

Perfect for small accounts where API overhead matters:

```
⚡ ENTRY OPERATIONS: 3s interval, 20 trades/min, 0 API points
🚪 EXIT OPERATIONS: 3s interval, 20 trades/min, 0 API points
📈 MONITORING: 30s interval, 2 checks/min, 1 API point
🔍 QUERIES: 15s interval, 4 queries/min, 1 API point

💰 API BUDGET:
   • Total: 15 points/min
   • Reserve: 5 points
   • Monitoring: 20%
   • Queries: 80%
```

**Optimizations:**
- Balance caching enabled (60s TTL)
- Minimal monitoring to save API points
- Prioritizes trade execution over frequent balance checks

### STANDARD Mode ($100-$1,000)

Balanced for medium accounts:

```
⚡ ENTRY OPERATIONS: 2s interval, 30 trades/min, 0 API points
🚪 EXIT OPERATIONS: 2s interval, 30 trades/min, 0 API points
📈 MONITORING: 10s interval, 6 checks/min, 1 API point
🔍 QUERIES: 5s interval, 12 queries/min, 1 API point

💰 API BUDGET:
   • Total: 15 points/min
   • Reserve: 3 points
   • Monitoring: 40%
   • Queries: 60%
```

**Optimizations:**
- Regular monitoring for position management
- Frequent queries for order status
- Good balance between visibility and API efficiency

### AGGRESSIVE Mode ($1,000+)

High-frequency for professional accounts:

```
⚡ ENTRY OPERATIONS: 1s interval, 60 trades/min, 0 API points
🚪 EXIT OPERATIONS: 1s interval, 60 trades/min, 0 API points
📈 MONITORING: 5s interval, 12 checks/min, 1 API point
🔍 QUERIES: 3s interval, 20 queries/min, 1 API point

💰 API BUDGET:
   • Total: 15 points/min
   • Reserve: 2 points
   • Monitoring: 50%
   • Queries: 50%
```

**Optimizations:**
- Maximum trade execution speed
- Real-time monitoring
- Frequent position updates
- Equal balance between monitoring and queries

## Benefits

### 💰 Cost Savings for Small Accounts

LOW_CAPITAL mode reduces monitoring API calls by **80%**:
- STANDARD: 6 balance checks per minute
- LOW_CAPITAL: 2 balance checks per minute

For a $50 account running 24/7:
- STANDARD: ~8,640 API points/day on monitoring
- LOW_CAPITAL: ~2,880 API points/day on monitoring
- **Savings: 67% reduction in monitoring API usage**

### ⚡ Faster Trade Execution

Entry and exit operations can execute rapidly since they're FREE:
- No artificial delays for trade placement
- Only rate-limited to prevent nonce collisions (1-3s)
- Monitoring operations don't slow down trading

### 📊 Smart API Budget Allocation

API points are reserved for what matters:
- Trading operations: Unlimited (0 points)
- Order queries: 60-80% of budget
- Monitoring: 20-40% of budget
- Always maintain reserve buffer

### 🎯 Account-Specific Optimization

The system recognizes that different account sizes have different priorities:
- Small accounts ($20-100): Minimize overhead, prioritize execution
- Medium accounts ($100-1000): Balance monitoring with efficiency
- Large accounts ($1000+): Maximum visibility and responsiveness

## Manual Override

You can manually specify a rate profile in your code:

```python
from bot.kraken_rate_profiles import KrakenRateMode, get_kraken_rate_profile

# Force LOW_CAPITAL mode regardless of balance
profile = get_kraken_rate_profile(mode=KrakenRateMode.LOW_CAPITAL)

# Force AGGRESSIVE mode
profile = get_kraken_rate_profile(mode=KrakenRateMode.AGGRESSIVE)
```

## Monitoring

The system logs rate limiting activity:

```
📊 Rate limit for AddOrder (entry): 2.0s
🛡️ Rate limiting (entry): sleeping 150ms between Kraken calls

📊 Rate limit for Balance (monitoring): 10.0s
🛡️ Rate limiting (monitoring): sleeping 8500ms between Kraken calls
```

## Technical Implementation

### Files Added/Modified

- **NEW**: `bot/kraken_rate_profiles.py` - Rate profile definitions
- **MODIFIED**: `bot/broker_manager.py` - Integration with KrakenBroker

### Key Changes

1. **Per-category rate tracking**: Separate intervals for each operation type
2. **Auto-selection logic**: Profile selection based on account balance
3. **Category-aware API calls**: All Kraken API calls specify their category
4. **Backward compatible**: Falls back to default 1s rate limit if profiles unavailable

## Future Enhancements

### Possible Improvements

1. **Dynamic profile switching**: Adjust profile when balance changes significantly
2. **Redis-based rate limiting**: Share rate limits across multiple bot instances
3. **Tier-aware budgets**: Adjust for Kraken Tier 1+ accounts (higher API limits)
4. **Time-based profiles**: Different profiles for active trading hours vs monitoring hours

## Troubleshooting

### Issue: Too many API rate limit errors

**Solution**: The profile might be too aggressive for your Kraken tier
- Check your Kraken account tier
- Manually switch to a more conservative profile
- Increase reserve_points in profile

### Issue: Balance checks are too slow

**Solution**: Your profile might be too conservative
- If account balance > $100, verify STANDARD mode is selected
- Manually override to AGGRESSIVE mode if needed
- Check that `KrakenAPICategory.MONITORING` is being used

### Issue: Trades are being rate limited

**Solution**: Entry/exit operations shouldn't be heavily rate limited
- Verify category is set to `ENTRY` or `EXIT`
- Check logs for actual intervals being used
- Ensure Kraken API is not returning rate limit errors

## References

- Kraken API Documentation: https://docs.kraken.com/rest/
- Kraken API Rate Limits: https://support.kraken.com/hc/en-us/articles/206548367
- NIJA Trading Documentation: `README.md`
- Small Account Preset: `bot/small_account_preset.py`

## Summary

The Kraken rate limiting profiles provide:

✅ **Separate budgets** for entry/exit vs monitoring operations
✅ **Low-capital mode** that minimizes API overhead for small accounts
✅ **Auto-selection** based on account balance
✅ **Smart allocation** of Kraken's 15 points/minute API budget
✅ **Fast execution** for trades (0 API points on Kraken)
✅ **Conservative monitoring** to save API budget

This ensures optimal performance across all account sizes while respecting Kraken's API rate limits.
