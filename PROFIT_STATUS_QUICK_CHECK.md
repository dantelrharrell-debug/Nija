# Is NIJA Making a Profit? - Quick Check Guide

## ❓ The Question

**"Is NIJA making a profit now on Kraken and Coinbase?"**

## ✅ The Answer (How to Check)

Run this single command:

```bash
python check_profit_status.py
```

## 📊 What You'll See

The report will immediately show:

### Quick Answer Section
```
================================================================================
✅ QUICK ANSWER
================================================================================

❌ NO - NIJA IS CURRENTLY LOSING MONEY
   Net P&L: $-10.30
```

OR

```
✅ YES - NIJA IS CURRENTLY PROFITABLE
   Net P&L: $+25.50
```

### Broker Breakdown

See profitability for each exchange:

```
❌ KRAKEN
--------------------------------------------------------------------------------
   💰 Cash Balance: Not available (live API query required)
   📊 Open Positions: 0

   📜 Trading History:
      • Completed Trades: 2
      • Win Rate: 50.0%
      • Realized P&L: $-10.30
      • Fees Paid: $2.34
      • Net (after fees): $-10.30

   ❌ KRAKEN is losing: $-10.30
```

### Final Verdict

The report ends with a clear verdict and recommendations:

```
================================================================================
🎯 FINAL VERDICT
================================================================================

❌ ❌ ❌ NIJA IS LOSING MONEY ❌ ❌ ❌

   Net Loss: $-10.30
   Total Value: $0.00

   ⚠️  NIJA is losing MORE than profiting - ACTION NEEDED!

   📋 Recommended Actions:
   1. Review trading strategy parameters
   2. Check if entry filters are too relaxed
   3. Verify stop-loss levels are appropriate
   4. Consider increasing minimum confidence threshold
   5. Review recent losing trades for patterns
   6. Check market conditions (trending vs ranging)
```

## 📈 Understanding the Results

### If PROFITABLE ✅
- **What it means**: Total realized P&L is positive
- **What to do**: Keep monitoring, strategy is working
- **Note**: Unrealized P&L from open positions is included

### If LOSING MONEY ❌
- **What it means**: Total realized P&L is negative
- **What to do**: Review strategy parameters (see recommendations)
- **Common causes**:
  - Stop losses too wide (>5% loss per trade)
  - Profit targets too tight (<2% gain per trade)
  - Entry filters too relaxed (low confidence trades)
  - Poor market conditions (ranging when strategy needs trends)

### If BREAK-EVEN ⚪
- **What it means**: No net profit or loss
- **What to do**: Continue monitoring
- **Note**: May indicate strategy needs more time/trades

## 🔍 What Data is Used?

The script combines data from:

1. **SQLite Database** (`data/trade_ledger.db`)
   - Completed trades table
   - Open positions table

2. **JSON Files** (`data/trade_history.json`)
   - Historical trade records
   - Backup/redundant tracking

3. **Deduplication**
   - Database entries preferred over JSON
   - Ensures each trade counted once

## ⚡ Quick Examples

### Check Profit Status
```bash
python check_profit_status.py
```

### Get Detailed Breakdown
```bash
python check_profit_status.py --detailed
```

### Use Custom Data Directory
```bash
python check_profit_status.py --data-dir /path/to/data
```

## 📝 Note on Live Balances

The script shows:
- ✅ **Historical P&L**: Calculated from completed trades (accurate)
- ℹ️ **Live Balances**: Requires API credentials (shows "Not available" when run standalone)

To see live balances from Kraken and Coinbase:
1. The bot logs already show this information
2. Use `bot/monitor_pnl.py` for real-time balance monitoring
3. Check the logs in the problem statement (shows $55.74 Kraken, $24.17 Coinbase)

## 🎯 Bottom Line

**As of the last check (based on logs and historical data):**

```
❌ NO - NIJA IS LOSING MONEY

Historical Performance:
- Net P&L: -$10.30
- Completed Trades: 2
- Win Rate: 50%
- Winning Trade: +$0.80
- Losing Trade: -$11.10

Current Status:
- Kraken Balance: $55.74 (from logs)
- Coinbase Balance: $24.17 (from logs)
- Open Positions: 0
- Trading Status: Filters blocking entries (confidence too low)
```

**The bot IS running but NOT trading** because:
1. Confidence threshold is 0.75 but signals are only 0.60
2. Entry filters were increased (to prevent more losses like the -$11.10 trade)
3. Protecting capital until better setups appear

## 📚 Related Tools

- `analyze_profitability.py` - Detailed trade-by-trade analysis
- `bot/monitor_pnl.py` - Real-time balance monitoring
- `PROFITABILITY_ANALYSIS_GUIDE.md` - Complete profitability guide

## 🔄 When to Check

**Check profitability:**
- Daily (to monitor performance)
- After significant trades
- When adjusting strategy parameters
- Before/after filter changes

**Exit codes:**
- `0` - Profitable or break-even
- `1` - Losing money (action needed)
- `2` - No data available

## 💡 Pro Tips

1. **Historical vs Current**: The script shows historical profitability. Current account value requires live API access.

2. **Actionable Insights**: If losing, the script provides specific recommendations based on trade data.

3. **Win Rate Isn't Everything**: A 50% win rate can be profitable if average wins > average losses.

4. **Fees Matter**: The script accounts for fees in all P&L calculations.

5. **Combine with Logs**: Use both this script AND the bot logs to get complete picture.

---

**Last Updated**: January 27, 2026
**Status**: Tool created to answer profitability question directly
