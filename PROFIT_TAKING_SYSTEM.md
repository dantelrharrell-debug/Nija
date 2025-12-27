# NIJA Profit-Based Exit System

## Overview

NIJA now includes an intelligent profit-based exit system that automatically sells positions when they hit profit targets or stop losses. This solves the problem where positions would go from profit to loss because the bot didn't know when to sell.

## How It Works

### Position Tracking

1. **Entry Tracking**: When NIJA buys a cryptocurrency, it records:
   - Entry price
   - Quantity purchased
   - USD value
   - Entry timestamp
   - Strategy used

2. **Persistent Storage**: All position data is saved to `positions.json` so it survives bot restarts

3. **Automatic Sync**: On startup, the tracker syncs with Coinbase to remove any positions that were sold manually or no longer exist

### Profit Targets (Stepped Exits)

NIJA uses a stepped profit-taking approach to lock in gains progressively:

- **+0.5%**: First profit target - exit entire position
- **+1.0%**: Second profit target - exit entire position  
- **+2.0%**: Third profit target - exit entire position
- **+3.0%**: Fourth profit target - exit entire position

**Why Stepped Exits?**
- Locks in quick gains before price reverses
- Frees up capital faster for new opportunities
- Reduces emotional decision-making
- Compounds profits more aggressively

### Stop Loss

- **-2.0%**: Automatic stop loss - exit entire position to cut losses
- **-1.0%**: Warning logged (approaching stop loss)

### Exit Priority

The bot checks exits in this order:

1. **Small positions** (< $1 USD value) - Always exit
2. **Profit targets** - From highest to lowest (3%, 2%, 1%, 0.5%)
3. **Stop loss** - At -2.0%
4. **RSI extremes** - Overbought (>70) or oversold (<30)
5. **Weak market conditions** - Failed market filters

## Monitoring

### Check Position Tracker Status

```bash
python check_position_tracker.py
```

This shows:
- All tracked positions
- Entry price vs current price
- Current P&L (dollars and percentage)
- Which profit targets have been hit
- Which positions should be sold

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
  Entry Time:   2025-12-27T12:00:00
  Current Price: $97,500.00
  Current Value: $101.23
  P&L: 🟢 $+1.23 (+1.23%)
  🎯 PROFIT TARGET +1.0% HIT - SHOULD SELL!

Symbol: ETH-USD
  Entry Price:  $3,450.00
  Quantity:     0.02898551
  Entry Value:  $100.00
  Entry Time:   2025-12-27T11:45:00
  Current Price: $3,380.00
  Current Value: $98.00
  P&L: 🔴 $-2.00 (-2.00%)
  🛑 STOP LOSS -2.0% HIT - SHOULD SELL!

======================================================================
Total P&L: $-0.77
======================================================================
```

## Bot Logs

The bot now shows detailed P&L information in its logs:

```
[2025-12-27 12:30:15] 📊 Managing 2 open position(s)...
[2025-12-27 12:30:15]    Analyzing BTC-USD...
[2025-12-27 12:30:15]    BTC-USD: 0.00103827 @ $97,500.00 = $101.23
[2025-12-27 12:30:15]    💰 P&L: $+1.23 (+1.23%) | Entry: $96,432.50
[2025-12-27 12:30:15]    🎯 PROFIT TARGET HIT: BTC-USD at +1.23% (target: +1.0%)
[2025-12-27 12:30:15] 🔴 CONCURRENT EXIT: Selling 1 positions NOW
[2025-12-27 12:30:16]   ✅ BTC-USD SOLD successfully!
```

## Configuration

### Profit Targets

Profit targets are configured in `/home/runner/work/Nija/Nija/bot/trading_strategy.py`:

```python
# STEPPED PROFIT TAKING
if pnl_percent >= 3.0:
    # Exit at +3.0%
elif pnl_percent >= 2.0:
    # Exit at +2.0%
elif pnl_percent >= 1.0:
    # Exit at +1.0%
elif pnl_percent >= 0.5:
    # Exit at +0.5%
```

To adjust targets, modify the percentages in `trading_strategy.py` (lines 315-340).

### Stop Loss

Stop loss is configured at line 360:

```python
elif pnl_percent <= -2.0:
    # Stop loss at -2.0%
```

## Files Modified

1. **`bot/position_tracker.py`** (NEW)
   - Core position tracking module
   - Persists entry prices to `positions.json`
   - Calculates P&L on demand

2. **`bot/broker_manager.py`**
   - Integrated position tracker into CoinbaseBroker
   - Tracks all BUY orders automatically
   - Tracks all SELL orders for cleanup

3. **`bot/trading_strategy.py`**
   - Added profit-based exit logic
   - Checks P&L before RSI/market checks
   - Logs detailed P&L information

4. **`check_position_tracker.py`** (NEW)
   - Utility script to view tracked positions
   - Shows current P&L and profit targets

## Troubleshooting

### Position Not Tracked

**Symptom**: Bot says "Could not calculate P&L for SYMBOL"

**Causes**:
1. Position was bought before profit tracking was added
2. `positions.json` was deleted
3. Bot was restarted and position was already owned

**Solution**:
- The bot will still use RSI and market condition exits
- New buys will be tracked automatically
- Manually bought positions won't have entry prices

### Positions.json Missing

**Symptom**: No tracked positions even though bot owns crypto

**Solution**:
1. The file is created automatically on first buy
2. Check `/home/runner/work/Nija/Nija/positions.json`
3. Run `check_position_tracker.py` to verify

### Wrong Entry Price

**Symptom**: Entry price doesn't match actual purchase price

**Causes**:
1. Multiple buys of same symbol (uses weighted average)
2. Partial fills

**Solution**:
- This is expected behavior for position averaging
- The weighted average is the correct cost basis
- Check `num_adds` field in tracker

## Future Enhancements

Potential improvements for v7.2:

1. **Partial exits**: Exit 50% at +1%, 50% at +2%
2. **Trailing stops**: Move stop to breakeven after +1%
3. **Time-based exits**: Force exit after N hours
4. **Fee awareness**: Account for Coinbase fees in P&L
5. **Performance analytics**: Track win rate, profit factor, etc.

## Technical Details

### Position Tracker Data Structure

```json
{
  "positions": {
    "BTC-USD": {
      "entry_price": 96432.50,
      "quantity": 0.00103827,
      "size_usd": 100.00,
      "first_entry_time": "2025-12-27T12:00:00",
      "last_entry_time": "2025-12-27T12:00:00",
      "strategy": "APEX_v7.1",
      "num_adds": 0
    }
  },
  "last_updated": "2025-12-27T12:30:15"
}
```

### Thread Safety

The position tracker uses a threading lock to prevent race conditions when:
- Multiple positions are being sold concurrently
- Bot is reading and writing positions simultaneously

### Persistence

- Atomic writes (tmp file + rename) prevent corruption
- JSON format for human readability
- Automatically loaded on broker initialization

## Summary

The profit-based exit system gives NIJA the ability to:
- ✅ Know when a position is profitable
- ✅ Automatically sell at profit targets
- ✅ Cut losses before they grow
- ✅ Lock in gains progressively
- ✅ Free up capital faster for new trades

This should prevent the situation where "NIJA bought 2 trades for profit, now they're in the red losing money."
