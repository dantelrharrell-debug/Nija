# NIJA Profitability Analysis Guide

## Overview

This guide explains how to check if NIJA is making more profit than losses using the profitability analysis tool.

## Quick Start

### Basic Analysis

Run the profitability analyzer to see if NIJA is profitable:

```bash
python analyze_profitability.py
```

This will show you:
- ✅ **PROFITABLE** - Making more profit than losses (everything is fine)
- ❌ **LOSING MONEY** - Losing more than profiting (action required)
- ⚪ **BREAK-EVEN** - No net profit or loss

### Detailed Analysis

For a detailed breakdown of all trades:

```bash
python analyze_profitability.py --detailed
```

### Export to CSV

Export trade history to CSV for further analysis:

```bash
python analyze_profitability.py --export-csv
```

The CSV file will be saved in `data/nija_trades_YYYYMMDD_HHMMSS.csv`

## Understanding the Report

### Trade Summary
- **Total Completed Trades**: Number of closed positions
- **Winning Trades**: Trades with positive P&L
- **Losing Trades**: Trades with negative P&L
- **Win Rate**: Percentage of winning trades

### Financial Summary
- **Total Net P&L**: Overall profit or loss after fees
- **Total Fees Paid**: Sum of all trading fees
- **Average Win/Loss**: Average profit/loss per trade
- **Largest Win/Loss**: Best and worst single trade
- **Profit Factor**: Ratio of total wins to total losses (higher is better)

### Recent Trades
Shows the last 10 trades with:
- 🟢 Green = Profitable trade
- 🔴 Red = Losing trade
- ⚪ White = Break-even trade

## Current Status (As of 2026-01-26)

**❌ NIJA IS CURRENTLY LOSING MONEY**

- **Net Loss**: -$10.30
- **Win Rate**: 50% (1 win, 1 loss)
- **Total Fees**: $2.34
- **Problem**: Single large loss (-$11.10) outweighs small win (+$0.80)

### Completed Trades Analysis

1. **ETH-USD** (Loss)
   - Entry: $103.65 → Exit: $93.32
   - Net P&L: **-$11.10** (-11.10%)
   - Exit Reason: Stop loss hit
   - **Issue**: Stop loss triggered with -10.62% loss

2. **BTC-USD** (Win)
   - Entry: $50,000 → Exit: $51,000
   - Net P&L: **+$0.80** (+0.80%)
   - Exit Reason: Take profit hit
   - **Issue**: Only 2% gain before exit

### Root Cause Analysis

The current loss is due to:
1. **Risk/Reward Imbalance**: Losing -11.10% on losses vs winning only +0.80%
2. **Stop Loss Too Loose**: Allowing -10.62% loss on ETH trade
3. **Profit Target Too Tight**: Taking only +2% profit on BTC trade (before fees)
4. **Poor Profit Factor**: 0.07 (should be > 1.5 for profitable trading)

## Recommended Actions

### Immediate Actions Required

1. **Adjust Stop Loss Levels**
   - Current: Allowing ~10% loss per trade
   - Recommended: Tighten to 2-3% maximum loss
   - Location: `bot/risk_manager.py` or strategy configuration

2. **Widen Profit Targets**
   - Current: Taking profits at ~2% gain
   - Recommended: Target at least 4-6% gain (2:1 reward-to-risk ratio)
   - Location: `bot/nija_apex_strategy_v71.py` or profit-taking configuration

3. **Review Entry Filters**
   - Ensure entering only high-quality setups
   - Check market regime filters
   - Verify signal strength requirements

4. **Position Sizing**
   - Consider reducing position size while optimizing
   - Current: $100 per trade (from examples)
   - This limits risk during adjustment period

### Long-Term Improvements

1. **Implement Trailing Stops**
   - Protect profits as they grow
   - Reduce losses by moving stop loss to break-even

2. **Add Win Rate Monitoring**
   - Alert if win rate drops below 50%
   - Auto-reduce position size during losing streaks

3. **Risk/Reward Ratio Enforcement**
   - Require minimum 2:1 reward-to-risk before entry
   - Reject trades with poor risk/reward profiles

4. **Strategy Backtesting**
   - Test parameter changes on historical data
   - Validate improvements before live deployment

## Monitoring Profitability

### Automated Monitoring

Add to your startup script or cron job:

```bash
# Check profitability daily
0 0 * * * cd /path/to/Nija && python analyze_profitability.py >> logs/profitability.log 2>&1
```

### Manual Checks

Run the analyzer:
- After each trading session
- Before making strategy changes
- When reviewing bot performance
- After significant market events

### Integration with Bot

You can integrate profitability checks into the main bot:

```python
from analyze_profitability import ProfitabilityAnalyzer

# In your main bot loop
analyzer = ProfitabilityAnalyzer()
trades = analyzer.load_trades()
stats = analyzer.calculate_stats(trades)

if stats.total_pnl < 0:
    logger.warning(f"⚠️ Bot is losing money: ${stats.total_pnl:.2f}")
    # Take action: reduce position size, tighten filters, etc.
```

## Exit Codes

The script returns different exit codes for automation:

- **0**: Profitable or break-even (everything OK)
- **1**: Losing money (action required)
- **2**: No trades found (cannot determine)

Use in scripts:

```bash
if python analyze_profitability.py; then
    echo "Bot is profitable, continue trading"
else
    echo "Bot is losing, review needed"
    # Send alert, stop bot, etc.
fi
```

## Data Sources

The analyzer checks:
1. **SQLite Database**: `data/trade_ledger.db` (completed_trades table)
2. **JSON File**: `data/trade_history.json` (legacy format)

Duplicate trades are automatically removed (database takes priority).

## Troubleshooting

### "No Completed Trades Found"

This means:
- NIJA hasn't closed any positions yet
- All trades are still open (unrealized P&L)
- Trade tracking may not be configured

**Solution**: Wait for positions to close or check profit-taking configuration

### "Cannot Load Database"

**Solution**: Ensure `data/trade_ledger.db` exists and is not corrupted

### "Incorrect P&L Calculations"

**Solution**: Verify that entry/exit fees are being tracked correctly

## Related Documentation

- [Trade Ledger Documentation](TRADE_LEDGER_README.md)
- [Profit Optimization Guide](PROFIT_OPTIMIZATION_GUIDE.md)
- [Risk Management Guide](RISK_PROFILES_GUIDE.md)
- [APEX Strategy Documentation](APEX_V71_DOCUMENTATION.md)

## Support

For issues or questions:
1. Check trade ledger integrity: `python -c "import sqlite3; conn = sqlite3.connect('data/trade_ledger.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM completed_trades'); print(f'Completed trades: {cursor.fetchone()[0]}')"`
2. Review bot logs for trade execution errors
3. Verify profit-taking is configured correctly

---

**Remember**: The goal is for NIJA to make MORE profit than losses. This tool helps you quickly determine if that's happening and what actions to take if it's not.
