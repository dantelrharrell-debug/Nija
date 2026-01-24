# Fix Summary: Coinbase Balance Fetching Issue

## Problem Description

The NIJA trading bot was incorrectly showing **zero balance** for existing cryptocurrency positions on Coinbase Advanced Trade, despite those positions actually existing on the exchange. This caused the bot to:

1. Mark these positions as "phantom positions"
2. Clear them from the position tracker without selling
3. Leave losing positions open on the exchange
4. Cause financial losses to the user

### Example from Logs

```
2026-01-24 22:46:31 | WARNING | ⚠️ PRE-FLIGHT WARNING: Zero CAKE balance shown (available: 0.00000000)
2026-01-24 22:46:31 | WARNING |    ⚠️ LIKELY PHANTOM: Tracked 5.66703762 CAKE but balance is zero
2026-01-24 22:46:36 | WARNING |    🧹 PHANTOM POSITION DETECTED: Zero balance but position tracked
2026-01-24 22:46:36 | WARNING |    Clearing CAKE-USD from position tracker (likely already sold/transferred)
2026-01-24 22:46:36 | INFO |   💨 CAKE-USD SKIPPED (dust position - too small to sell)
```

**The positions were actually still on Coinbase and still losing money**, but the bot couldn't see them.

## Root Cause

The bot was using **incorrect field names** when parsing the Coinbase Advanced Trade API's `get_portfolio_breakdown` response. The code was looking for fields that don't exist in the API response:

### Incorrect Field Names (What the Code Was Using)
- `available_to_trade_base`
- `hold_base`
- `available_to_trade`
- `hold`

### Correct Field Names (Per Coinbase API Documentation)
- `available_to_trade_crypto` - Amount freely tradable in crypto units
- `total_balance_crypto` - Total balance in crypto units (includes available + held)

When the code looked for non-existent fields, it got `None` values, which were converted to `0.0`, making the bot think all crypto balances were zero.

## Solution

Updated two critical methods in `bot/broker_manager.py`:

### 1. `_get_account_balance_detailed()` Method
This method fetches account balances from Coinbase. Changed lines ~1666-1730 to:

**Before:**
```python
base_available = pos.get('available_to_trade_base') if pos.get('available_to_trade_base') is not None else pos.get('available_to_trade')
base_held = pos.get('hold_base') if pos.get('hold_base') is not None else pos.get('hold')
```

**After:**
```python
base_available = pos.get('available_to_trade_crypto')
base_total = pos.get('total_balance_crypto')
```

**Key Change:** Now uses `total_balance_crypto` which includes the **full position** (available + held), ensuring the bot can see the entire position.

### 2. `get_positions()` Method
This method retrieves current crypto positions. Changed lines ~3626-3650 to use the same correct field names.

**Before:**
```python
base_avail = pos.get('available_to_trade') or pos.get('available_to_trade_base')
```

**After:**
```python
base_avail = pos.get('available_to_trade_crypto')
base_total = pos.get('total_balance_crypto')
```

## Additional Improvements

1. **Debug Logging:** Added logging to show what field values are received from the API
2. **Safety Check:** Added `max(0, ...)` to prevent negative held amounts from API inconsistencies
3. **Better Fallback Logic:** Improved handling when only partial data is available
4. **Documentation:** Created `validate_coinbase_field_names.py` to document the fix

## Testing & Validation

1. ✅ Python syntax check passed
2. ✅ Code review completed and feedback addressed
3. ✅ Security scan (CodeQL) passed with 0 alerts
4. ✅ Validation script created and tested

## Impact

**Before the fix:**
- Bot saw 0.00000000 balance for all crypto positions
- Positions marked as "phantom" and cleared from tracker
- No sells executed
- Positions left to lose money on exchange

**After the fix:**
- Bot correctly reads crypto balances from `total_balance_crypto` field
- Positions detected and tracked properly
- Sells can execute when needed
- Risk management functions correctly

## Files Changed

1. `bot/broker_manager.py` - Fixed field names in two methods
2. `validate_coinbase_field_names.py` - New validation/documentation script
3. `FIX_SUMMARY_COINBASE_BALANCE.md` - This summary document

## References

- Coinbase Advanced Trade API Documentation: https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/portfolios/get-portfolio-breakdown
- Issue identified: January 2026
- SDK Version: `coinbase-advanced-py==1.8.2`

## Prevention

The `validate_coinbase_field_names.py` script serves as documentation to prevent this issue from recurring. If Coinbase changes their API fields in the future, developers should:

1. Check the official API documentation
2. Run the validation script
3. Update field names if needed
4. Test with small positions first

## Verification Steps for Deployment

After deploying this fix:

1. Monitor logs for the debug messages showing `total_balance_crypto` values
2. Verify positions are no longer marked as "phantom"
3. Confirm sells execute successfully when exit conditions are met
4. Check that balance checking works for all crypto assets

## Critical Note

This fix addresses the **symptom** (positions not being sold) by fixing the **root cause** (incorrect API field names). The phantom position detection logic itself is correct and should remain in place to handle truly phantom positions (e.g., positions manually transferred off exchange).
