# Quick Start: Dust Position Cleanup

## Problem
You have **8 consecutive trades** (at the maximum limit), but only **2 are winning trades** and **6 are dust positions** (very small value). This prevents the bot from opening new winning trades.

## Solution
The dust threshold has been increased from $0.001 to $1.00, so positions below $1.00 won't count against your 8-position limit.

## How to Clean Up Dust Positions

### Step 1: Check Your Current Positions
```bash
python check_dust_positions.py
```

This will show:
- All your current positions sorted by value
- Which ones are "dust" (< $1.00)
- How many slots will be freed

**Example Output:**
```
📊 POSITION BREAKDOWN (by value)
======================================================================

 1. BTC-USD   $    12.5000  |   0.00041230 @ $  30321.45  ✅ WINNING
 2. ETH-USD   $     8.2000  |   0.00456789 @ $   1794.33  ✅ WINNING
 3. DOGE-USD  $     0.0600  |   5.45454545 @ $      0.011  🗑️ DUST
 4. HBAR-USD  $     0.0400  |   0.72727273 @ $      0.055  🗑️ DUST
 5. UNI-USD   $     0.0400  |   0.00869565 @ $      4.600  🗑️ DUST
 6. LINK-USD  $     0.1200  |   0.01090909 @ $     11.000  🗑️ DUST
 7. DOT-USD   $     0.1300  |   0.02380952 @ $      5.460  🗑️ DUST
 8. ADA-USD   $     0.0500  |   0.12500000 @ $      0.400  🗑️ DUST

💡 RECOMMENDATION
🗑️ 6 DUST POSITIONS TO CLOSE:
   - DOGE-USD: $0.0600
   - HBAR-USD: $0.0400
   - UNI-USD: $0.0400
   - LINK-USD: $0.1200
   - DOT-USD: $0.1300
   - ADA-USD: $0.0500

💡 Closing these would free up 6 position slots
   Allowing 6 more winning trades
```

### Step 2: Preview What Will Be Closed (Dry Run)
```bash
python close_dust_positions.py --dry-run
```

This shows what would be closed **without actually closing anything**. Safe to run anytime.

### Step 3: Close the Dust Positions
```bash
python close_dust_positions.py
```

This will:
- Sell all positions worth less than $1.00
- Use market orders for instant execution
- Report how many slots were freed

**Example Output:**
```
🔥 CLOSING 6 DUST POSITIONS
======================================================================

[1/6] Closing DOGE-USD...
   Balance: 5.45454545
   Value:   $0.0600
   ✅ SOLD! Order ID: abc123

[2/6] Closing HBAR-USD...
   Balance: 0.72727273
   Value:   $0.0400
   ✅ SOLD! Order ID: def456

... (continues for all 6 dust positions)

✅ CLEANUP COMPLETE
======================================================================
🗑️  Closed:  6 positions
❌ Failed:  0 positions
💰 Freed:   $0.4100
📈 Slots:   6 position slots now available

💡 Position slots freed! The bot can now open more winning trades.
   The 8-position limit will now count only positions ≥ $1.00
```

### Step 4: Verify Cleanup Worked
```bash
python check_dust_positions.py
```

Should now show only your 2 winning positions, with 6 slots available.

## What Happens Next?

After cleanup:
- ✅ Dust positions are sold and converted to USD
- ✅ You now have 6 available position slots
- ✅ The bot can open 6 new winning trades
- ✅ Only positions ≥ $1.00 count against the 8-position limit

The bot will automatically:
- Resume scanning for new trades
- Open up to 6 more positions (up to the 8-position limit)
- Only count positions worth ≥ $1.00

## Advanced Options

### Custom Threshold
Want to be more aggressive and only keep positions ≥ $5.00?
```bash
python close_dust_positions.py --threshold 5.00
```

This will close all positions below $5.00.

### Help
```bash
python close_dust_positions.py --help
```

## Safety Notes

- ✅ The cleanup script uses market orders (instant execution)
- ✅ Each position is handled individually with error handling
- ✅ Rate limiting prevents API throttling
- ✅ You can always check positions before/after with `check_dust_positions.py`
- ✅ Dry run mode lets you preview before executing

## Summary

1. Check positions: `python check_dust_positions.py`
2. Preview cleanup: `python close_dust_positions.py --dry-run`
3. Execute cleanup: `python close_dust_positions.py`
4. Verify results: `python check_dust_positions.py`

You'll go from **8 positions (2 winning + 6 dust)** to **2 positions with 6 slots available** for new winning trades! 🚀
