# NIJA Profit-Taking Fix - Complete Summary

## Problem Solved

**Original Issue**: "Why didnt nija sell the 2 trades it just bought for profit now there in the red lossing me money when will nija sell them"

**Root Cause**: NIJA Trading Bot could not calculate profit/loss on positions because Coinbase API doesn't return entry prices in the `get_positions()` response. The bot only had exit logic based on technical indicators (RSI, market conditions), not profit targets.

## Solution Delivered

### ✅ New Profit-Based Exit System

The bot now:
1. **Tracks entry prices** for all positions in a persistent JSON file
2. **Calculates real-time P&L** (profit/loss) for each position
3. **Automatically sells** when profit targets or stop losses are hit
4. **Preserves data** across bot restarts
5. **Syncs automatically** with Coinbase to clean up orphaned positions

### 🎯 Profit Targets (Stepped Exits)

NIJA will now automatically sell entire positions at these profit levels:
- **+0.5% profit** → SELL
- **+1.0% profit** → SELL
- **+2.0% profit** → SELL
- **+3.0% profit** → SELL

### 🛑 Stop Loss Protection

NIJA will automatically cut losses at:
- **-2.0% loss** → SELL (stop loss)
- **-1.0% loss** → WARNING logged (approaching stop loss)

## What Changed

### New Files Created

1. **`bot/position_tracker.py`** (333 lines)
   - Persistent position tracking with JSON storage
   - Entry price tracking with weighted averages
   - Real-time P&L calculation
   - Thread-safe operations

2. **`check_position_tracker.py`** (105 lines)
   - Monitoring utility to view all tracked positions
   - Shows current P&L and which profit targets are hit
   - Run with: `python check_position_tracker.py`

3. **`PROFIT_TAKING_SYSTEM.md`** (240 lines)
   - Complete documentation of the profit-taking system
   - Usage examples and troubleshooting guide
   - Technical details and configuration options

### Files Modified

1. **`bot/broker_manager.py`**
   - Added position tracker initialization in CoinbaseBroker
   - Tracks all BUY orders automatically
   - Tracks all SELL orders for cleanup
   - Uses actual fill price when available (with fallback to market price)

2. **`bot/trading_strategy.py`**
   - Added profit-based exit logic BEFORE technical indicator checks
   - Integrated with position tracker for P&L calculations
   - Added shared configuration for profit targets (PROFIT_TARGETS)
   - Automatic position sync on startup
   - Detailed P&L logging for every position

## How It Works Now

### When NIJA Buys

```
[2025-12-27 14:30:15] 🎯 BUY SIGNAL: BTC-USD - size=$100.00
[2025-12-27 14:30:16] ✅ Order filled successfully: BTC-USD
[2025-12-27 14:30:16]    📊 Position tracked: entry=$96,432.50, size=$100.00
```

The entry price is now saved to `positions.json`.

### On Every Trading Cycle

```
[2025-12-27 14:35:15] 📊 Managing 2 open position(s)...
[2025-12-27 14:35:15]    Analyzing BTC-USD...
[2025-12-27 14:35:15]    BTC-USD: 0.00103827 @ $97,500.00 = $101.23
[2025-12-27 14:35:15]    💰 P&L: $+1.23 (+1.23%) | Entry: $96,432.50
[2025-12-27 14:35:15]    🎯 PROFIT TARGET HIT: BTC-USD at +1.23% (target: +1.0%)
```

NIJA now shows:
- Current quantity and price
- Dollar value of position
- **P&L in dollars and percentage**
- **Original entry price**
- **Which profit target was hit**

### When NIJA Sells for Profit

```
[2025-12-27 14:35:15] 🔴 CONCURRENT EXIT: Selling 1 positions NOW
[2025-12-27 14:35:15] [1/1] Selling BTC-USD (Profit target +1.0% hit (actual: +1.23%))
[2025-12-27 14:35:16]   ✅ BTC-USD SOLD successfully!
[2025-12-27 14:35:16]    📊 Position exit tracked
```

The position is removed from tracking after successful sell.

## Monitoring Your Positions

### Check Position Status

Run this command anytime to see your tracked positions:

```bash
python check_position_tracker.py
```

### Example Output

```
======================================================================
NIJA POSITION TRACKER STATUS
======================================================================

📊 2 tracked position(s):

Symbol: BTC-USD
  Entry Price:  $96,432.50
  Quantity:     0.00103827
  Entry Value:  $100.00
  Entry Time:   2025-12-27T14:30:15
  Current Price: $97,500.00
  Current Value: $101.23
  P&L: 🟢 $+1.23 (+1.23%)
  🎯 PROFIT TARGET +1.0% HIT - SHOULD SELL!

Symbol: ETH-USD
  Entry Price:  $3,450.00
  Quantity:     0.02898551
  Entry Value:  $100.00
  Entry Time:   2025-12-27T14:25:00
  Current Price: $3,380.00
  Current Value: $98.00
  P&L: 🔴 $-2.00 (-2.00%)
  🛑 STOP LOSS -2.0% HIT - SHOULD SELL!

======================================================================
Total P&L: $-0.77
======================================================================
```

## Important Notes

### Existing Positions

⚠️ **Positions bought BEFORE this fix was deployed will NOT have entry prices tracked.**

- They will still be managed using RSI and market condition exits
- New buys will be tracked automatically
- If you want to reset and start fresh, the bot will track all new positions going forward

### Position Tracking File

All entry prices are saved in: `/home/runner/work/Nija/Nija/positions.json`

This file:
- ✅ Survives bot restarts
- ✅ Automatically syncs with Coinbase on startup
- ✅ Uses atomic writes to prevent corruption
- ✅ Is human-readable JSON format

### Configuration

To adjust profit targets or stop loss, edit `/home/runner/work/Nija/Nija/bot/trading_strategy.py`:

```python
# Profit target thresholds (stepped exits)
PROFIT_TARGETS = [
    (3.0, "Profit target +3.0%"),
    (2.0, "Profit target +2.0%"),
    (1.0, "Profit target +1.0%"),
    (0.5, "Profit target +0.5%"),
]

# Stop loss thresholds
STOP_LOSS_THRESHOLD = -2.0  # Exit at -2% loss
STOP_LOSS_WARNING = -1.0  # Warn at -1% loss
```

## What to Expect

### Before This Fix

1. Bot buys BTC at $96,432
2. Price goes up to $97,500 (+1.1% profit)
3. Bot sees RSI is neutral (50), keeps holding
4. Price drops back to $95,000 (-1.5% loss)
5. **You lose money** 😞

### After This Fix

1. Bot buys BTC at $96,432
2. Price goes up to $97,500 (+1.1% profit)
3. **Bot sees +1.1% profit, sells at +1.0% target** 🎯
4. **Profit locked in: +$1.10** 💰
5. Capital freed up for next trade ✅

## Testing Recommendations

1. **Monitor the first few trades** after deployment
2. **Check positions.json** to ensure tracking is working
3. **Run check_position_tracker.py** periodically to see P&L
4. **Watch logs** for profit target messages
5. **Verify sells are happening** at profit targets

## Troubleshooting

### "Could not calculate P&L for SYMBOL"

**Cause**: Position was bought before profit tracking was added

**Solution**: This is normal. New buys will be tracked. Old positions will use RSI/market exits.

### positions.json doesn't exist

**Cause**: No positions have been bought yet since the fix was deployed

**Solution**: Wait for the bot to make its first buy. The file will be created automatically.

### Wrong entry price shown

**Cause**: Multiple buys of the same symbol (uses weighted average)

**Solution**: This is correct behavior. The bot calculates a weighted average entry price when you add to a position.

## Files to Review

- **Code Changes**: See the GitHub PR at `copilot/investigate-ninja-trades` branch
- **Documentation**: Read `PROFIT_TAKING_SYSTEM.md` for full details
- **Monitoring**: Use `check_position_tracker.py` to view positions

## Summary

✅ **Problem Fixed**: NIJA now knows when to sell for profit
✅ **Profit Targets**: Sells at +0.5%, +1%, +2%, +3%
✅ **Stop Loss**: Cuts losses at -2%
✅ **Persistent**: Survives bot restarts
✅ **Monitored**: Check status anytime with utility script
✅ **Documented**: Complete documentation provided

Your trading bot will no longer hold winning positions until they become losers. It will lock in profits progressively and cut losses quickly.

---

**Deployment**: Ready to deploy to production
**Status**: All code reviews passed, ready for live testing
**Next Steps**: Deploy, monitor first few trades, adjust targets if needed
