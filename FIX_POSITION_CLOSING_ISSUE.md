# Fix for Position Closing Issue - December 23, 2025

## Problem
Bot was unable to close 13+ positions because exit orders kept failing with:
```
❌ PRE-FLIGHT CHECK FAILED: Insufficient [COIN] balance (X.XXX < Y.YYYY)
```

Example:
- Tried to sell 7.2353497 LTC
- Only had 7.1865 LTC available
- Difference: ~0.047 LTC (0.6% gap)

This pattern repeated for ALL positions attempting to close, causing a cascading failure where:
1. Exit orders failed → positions stayed open
2. 13 positions exceeded limit of 8
3. Emergency force-close triggered
4. All force-closes also failed with INSUFFICIENT_FUND
5. Bot stuck in infinite retry loop

## Root Cause Analysis

The gap between tracked position size and actual available balance comes from:

| Cause | Impact |
|-------|--------|
| **Partial fills** | Buy 100 units but only 99 executed | 
| **Trading fees** | Coinbase takes 0.5-1% from crypto side | 
| **Blockchain holds** | Funds locked during settlement | 
| **Position sync delay** | Tracking data stale vs Coinbase API | 
| **Rounding errors** | Floating point precision issues | 

Example scenario:
```
Entry: Bought 7.24 LTC @ $76.66
Fee: -0.005 LTC (0.07%)
Hold: -0.02 LTC (pending settlement)
Actual available: 7.185 LTC

Bot tracked: 7.235 LTC (pre-fees)
Attempted to sell: 7.235 LTC ← FAILS (only 7.185 available)
```

## Solutions Implemented

### FIX #1: Use Actual Available Balance Instead of Tracked Amount
**Location:** `broker_manager.py` lines 960-975

```python
# Get FRESH balance immediately before placing sell order
balance_snapshot = self.get_account_balance()
available_base = float(holdings.get(base_currency, 0.0))

# If available < tracked, USE AVAILABLE AMOUNT
if available_base < quantity:
    logger.warning(f"⚠️ Adjusting from {quantity} to {available_base}")
    quantity = available_base  # ← FIX #1
```

**Effect:** Eliminates pre-flight check failures by ensuring sell orders only use actual available crypto.

### FIX #2: Add Safety Buffer to Pre-Flight Check
**Location:** `broker_manager.py` lines 851-862

```python
# Add 2% safety buffer for fees/rounding
safety_buffer = quantity * 0.02
required_with_buffer = quantity + safety_buffer

if trading_balance < required_with_buffer:
    logger.error(f"❌ Insufficient: ${trading_balance} < ${required_with_buffer} (with 2% buffer)")
```

**Effect:** Prevents accepting orders that won't have enough to cover fees after filling.

### FIX #3: Use Larger Safety Margin on Exit Orders
**Location:** `broker_manager.py` lines 1032-1043

```python
# Use 0.5% safety margin (Coinbase typically charges 0.5-1%)
safety_margin = max(requested_qty * 0.005, 0.00000001)
trade_qty = max(0.0, requested_qty - safety_margin)

logger.info(f"Safety margin: {safety_margin:.8f} {base_currency} (0.5%)")
logger.info(f"Final trade qty: {trade_qty:.8f} {base_currency}")
```

**Effect:** Orders execute with room for fees instead of right at the limit.

## Deployment Changes

| File | Changes | Purpose |
|------|---------|---------|
| `bot/broker_manager.py` | Lines 851-1043 | Added all 3 fixes to pre-flight and exit logic |

## How It Works After Fix

### Scenario: Closing LTC Position (Same Example as Before)
```
Step 1: Pre-flight check (BUY order)
  Available: $175.50
  Required: $100.00
  Buffer: $2.00 (2%)
  Status: ✅ PASS ($175.50 > $102)

Step 2: Execute entry
  Actual filled: 7.18 LTC (not 7.24 due to fees)

Step 3: Exit attempt
  Tracked: 7.24 LTC
  Actual: 7.18 LTC
  FIX #1: Detect mismatch, use actual 7.18 LTC
  FIX #3: Apply 0.5% margin → 7.144 LTC
  Final sell: 7.144 LTC ← ✅ SUCCEEDS (actual available)
```

## Testing

After deployment, monitor logs for:

1. **Balance mismatch detection:**
   ```
   ⚠️ Balance mismatch: tracked 7.24000 but only 7.18000 available
   Difference: 0.06000 LTC (likely from partial fills or fees)
   SOLUTION: Adjusting sell size to actual available balance
   ```

2. **Safety margins being applied:**
   ```
   Safety margin: 0.03587 LTC (0.5%)
   Final trade qty: 7.14813 LTC
   ```

3. **Successful exit order:**
   ```
   📤 Placing SELL order: LTC-USD, base_size=7.14813
   [...]
   ✅ Order filled successfully
   ```

## Verification Checklist

- [ ] Restart bot
- [ ] Check logs for position closures (should succeed now)
- [ ] Monitor "EMERGENCY CLOSE" messages (should be successful)
- [ ] Verify positions decrease from 13 → 8 or lower
- [ ] Check Coinbase web UI: positions should reduce
- [ ] Look for NO more "INSUFFICIENT_FUND" errors

## Code Quality

- ✅ Maintains existing error handling
- ✅ All fixes are non-breaking (defensive layer)
- ✅ Enhanced logging for debugging
- ✅ Follows project conventions
- ✅ Comments explain each fix's purpose

## Next Steps

1. Deploy `bot/broker_manager.py`
2. Bot will auto-restart
3. Monitor logs for 2-5 minutes
4. Positions should start closing
5. If any still fail, check logs for other issues

## Questions?

If positions still won't close after this fix, check:
1. Are balances showing correctly in Coinbase API?
2. Are there pending settlement holds?
3. Is the Coinbase API rate limited?
4. Check `bot/nija.log` for detailed error messages
