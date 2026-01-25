# Fix: Tier Limit vs Kraken Minimum Conflict Resolution

## Problem Statement

The bot was placing trades that violated tier-based risk management limits when trading on Kraken.

### Example Scenario (from logs)
- **Account:** STARTER tier with $58.78 balance
- **Max allowed trade:** $8.82 (15% of balance per tier limits)
- **Trade request:** $10.58 
- **What happened:**
  1. Tier auto-resize reduced trade to $8.82 ✅ (within tier limits)
  2. Kraken minimum enforcement bumped it back to $10.00 ❌ (violating tier limits)
- **Result:** Trade executed at $10.00, exceeding the safe 15% limit
- **User complaint:** "Nija is for profit not losses"

## Root Cause

In `bot/broker_manager.py`, the order of operations allowed Kraken's minimum order enforcement to override tier-based risk management:

1. **First:** Tier auto-resize (lines 6720-6782) → reduces $10.58 to $8.82
2. **Then:** Kraken minimum enforcement (lines 6787-6804) → bumps $8.82 to $10.00
3. **Problem:** The second step overrode the first, defeating tier protection

## Solution Implemented

Modified the Kraken minimum enforcement logic to respect tier limits:

### Key Changes

1. **Added tracking flag** (line 6689):
   ```python
   tier_was_auto_resized = False
   ```

2. **Set flag when tier resize occurs** (line 6758):
   ```python
   if resized_size != order_size_usd:
       quantity = resized_size
       tier_was_auto_resized = True  # NEW
   ```

3. **Check flag before bumping to Kraken minimum** (lines 6802-6820):
   ```python
   if quantity < kraken_min:
       if tier_was_auto_resized:
           # REJECT the trade - cannot meet Kraken min without violating tier
           return {"status": "error", "error": "..."}
       else:
           # Safe to bump up to Kraken minimum
           quantity = kraken_min
   ```

### Logic Flow After Fix

```
Trade Request ($10.58)
        ↓
Tier Auto-Resize → $8.82 (within STARTER tier 15% limit)
        ↓
tier_was_auto_resized = True
        ↓
Kraken Minimum Check ($10.00 required)
        ↓
Is $8.82 < $10.00? YES
        ↓
Was trade tier-resized? YES
        ↓
❌ REJECT TRADE with clear error message
   "Cannot meet Kraken minimum without violating tier limits"
```

## Expected Behavior

### Before Fix
- Trade resized to $8.82, then bumped to $10.00
- Violates tier safety (17% of $58.78 instead of max 15%)
- Small accounts at risk of excessive losses

### After Fix  
- Trade resized to $8.82, then REJECTED
- Clear error explaining tier/Kraken conflict
- Small accounts protected from excessive risk
- User message: "Tier limits protect small accounts from excessive risk"

## Code Quality

- ✅ Used explicit flag instead of unreliable `locals()` check
- ✅ Clear comments explaining logic flow
- ✅ Specific exception handling
- ✅ Clean, maintainable code
- ✅ No unused variables

## Testing

Created comprehensive test script: `test_tier_kraken_conflict.py`

### Test Case 1: Conflict Scenario
- Balance: $58.78 (STARTER tier)
- Requested: $10.58
- Tier-adjusted: $8.82
- Kraken minimum: $10.00
- **Result:** ✅ Conflict detected, trade should be rejected

### Test Case 2: Valid Trade
- Balance: $100.00 (SAVER tier)  
- Requested: $12.00
- Tier-adjusted: $10.00 (10% of $100)
- Kraken minimum: $10.00
- **Result:** ✅ Trade allowed (meets both requirements)

All tests pass successfully.

## Security

- CodeQL scan: 0 alerts ✅
- No new vulnerabilities introduced
- Maintains existing security patterns

## Files Modified

1. **bot/broker_manager.py**
   - Added `tier_was_auto_resized` flag (line 6689)
   - Set flag during tier auto-resize (line 6758)
   - Check flag in Kraken minimum enforcement (lines 6802-6820)
   - Reject trades that would violate tier limits

2. **test_tier_kraken_conflict.py** (NEW)
   - Test conflict scenario (tier limit < Kraken minimum)
   - Test valid scenario (tier limit ≥ Kraken minimum)
   - Validates auto_resize_trade() function behavior

## Impact

### Positive
- ✅ Protects small accounts from excessive risk
- ✅ Tier-based risk management now works as intended
- ✅ Clear error messages help users understand limitations
- ✅ Maintains "profit not losses" philosophy

### Trade-offs
- ⚠️ Some trades will be rejected that previously would have executed
- ⚠️ Accounts with balance < $66.67 cannot trade on Kraken (STARTER tier max is $8.82, but Kraken min is $10)
- 💡 This is intentional - protecting users from taking trades too large for their account

## Recommendations

For users affected by this change:

1. **Option 1:** Increase account balance to at least $67-70 to meet both tier limits and Kraken minimums
2. **Option 2:** Use a different exchange with lower minimums (e.g., Coinbase has $2 minimum)
3. **Option 3:** Wait for account to grow through successful smaller trades on other exchanges

The tier system is designed to grow with your account - this protection ensures sustainable growth rather than risky oversized trades.

## Deployment Notes

- No database migrations required
- No environment variable changes needed
- Safe to deploy immediately
- Existing positions unaffected (only affects new trade entries)
- Backwards compatible with existing code

## Related Documentation

- `TIER_AND_RISK_CONFIG_GUIDE.md` - Tier system overview
- `TIER_EXECUTION_GUIDE.md` - Tier execution details  
- `KRAKEN_TRADING_GUIDE.md` - Kraken-specific requirements
- `STARTER_SAFE_PROFILE.md` - STARTER tier specifics
