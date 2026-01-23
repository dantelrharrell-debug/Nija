# Fix Verification Guide

## Issue: "No entry price tracked" Warning

### Problem Description
The bot was showing a warning: "⚠️ No entry price tracked for BNB-USD - attempting auto-import"

This prevented the bot from:
- Calculating accurate P&L for existing positions
- Properly exiting positions based on profit targets
- Picking up new trades because it couldn't free up capital

### Root Cause
The `get_real_entry_price()` method was not implemented in `CoinbaseBroker`, causing the auto-import logic to fall back to a safety default (current_price * 1.01), which artificially marked positions as losers.

### Solution Implemented
Added a fully functional `get_real_entry_price()` method to `CoinbaseBroker` that:
1. Fetches recent fills from Coinbase using `client.list_fills()`
2. Searches through the last 100 fills to find the most recent BUY order
3. Returns the actual entry price from the order history
4. Uses rate limiting to prevent API errors

## Verification Steps

### 1. Check Log Output
After deploying, monitor logs for positions that previously showed the warning:

**Before (Issue):**
```
2026-01-23 20:13:29 | WARNING | ⚠️ No entry price tracked for BNB-USD - attempting auto-import
2026-01-23 20:13:29 | WARNING | ⚠️ Using safety default entry price: $904.40 (current * 1.01)
2026-01-23 20:13:29 | WARNING | 🔴 This position will be flagged as losing and exited aggressively
```

**After (Fixed):**
```
2026-01-23 20:13:29 | WARNING | ⚠️ No entry price tracked for BNB-USD - attempting auto-import
2026-01-23 20:13:29 | INFO | ✅ Real entry price fetched: $893.07
2026-01-23 20:13:29 | INFO | ✅ AUTO-IMPORTED: BNB-USD @ $893.07
2026-01-23 20:13:29 | INFO | 💰 Immediate P&L: +0.00%
```

### 2. Verify Position Tracking
Check that positions are now being tracked properly:

```bash
# Check positions.json to see if BNB-USD is tracked
cat positions.json | grep -A5 "BNB-USD"
```

Should show proper entry price instead of inflated safety default.

### 3. Verify Bot Behavior
- ✅ Bot should calculate accurate P&L
- ✅ Bot should use proper profit targets (not aggressive exits)
- ✅ Bot should be able to sell positions when criteria are met
- ✅ Bot should be able to pick up new trades after selling

### 4. API Rate Limiting
Monitor for any 429 errors when fetching fills:

```bash
# Check for rate limit errors
grep -i "429\|rate limit" nija.log
```

Should not see increased rate limiting due to the new fills endpoint being rate-limited at 12 req/min.

## Test Manually

You can test the fix manually using the provided test script:

```bash
python3 test_entry_price_recovery.py
```

This will:
1. Connect to Coinbase
2. Attempt to fetch entry price for a test symbol
3. Test integration with position tracking
4. Display results

## Expected Outcomes

1. **Accurate Entry Price Recovery**: Positions that exist in Coinbase but aren't in positions.json will have their real entry prices recovered from order history

2. **Proper P&L Calculation**: The bot will calculate correct profit/loss percentages based on actual entry prices

3. **Normal Exit Logic**: Positions won't be flagged as "losers" just because they're auto-imported

4. **Ability to Trade**: The bot can properly manage positions and free up capital for new trades

## Rollback Plan

If issues occur, you can temporarily disable entry price recovery by:

1. Comment out the `get_real_entry_price` method call in `trading_strategy.py` (line 2374)
2. The bot will fall back to safety defaults (conservative exit behavior)

## Notes

- The fix retrieves the **most recent BUY fill** for a symbol
- For positions with multiple partial fills, this may not perfectly represent weighted average cost
- For long-term accuracy, use position tracking from the start of trades
- This fix is designed to recover orphaned positions, not replace proper position tracking

## Monitoring Checklist

After deployment, monitor these metrics for 24 hours:

- [ ] No increase in API rate limit errors
- [ ] Positions being tracked properly in positions.json
- [ ] Accurate P&L calculations in logs
- [ ] Normal exit behavior (not all positions marked as losers)
- [ ] Bot successfully executing new trades
- [ ] No "No entry price tracked" warnings (or successfully recovered when they occur)
