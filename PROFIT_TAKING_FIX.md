# Profit-Taking System Fix (Dec 27, 2025)

## Problem
The bot was not taking profits and the portfolio was bleeding losses. Positions in BAT, XLM, SOL, ETH, and BTC were losing value without automatic exits.

## Root Cause
1. **Missing Entry Prices**: Positions opened before the position tracker was implemented don't have entry prices recorded
2. **Profit-taking Disabled**: Without entry prices, the profit-taking logic doesn't run
3. **Conservative Fallback**: RSI-based exits only trigger at extremes (RSI>70 or RSI<30), allowing losses to accumulate

## Solution Implemented

### 1. Enhanced Fallback Profit-Taking (bot/trading_strategy.py)
- **Momentum-based exits**: Exit on RSI>60 + price below EMA9 (losing momentum after gains)
- **Downtrend exits**: Exit on RSI<40 + price below EMA21 (cutting losses in downtrends)
- **Aggressive profit-locking**: Don't wait for RSI>70, exit earlier when momentum reverses
- **Better logging**: Warn when positions lack entry prices and explain fallback logic

### 2. Import Tool (import_current_positions.py)
- Import existing positions into the position tracker
- Uses **current prices as entry prices** (starts P&L tracking from now)
- Interactive - asks before overwriting existing tracked positions
- Skips dust positions (< $0.50)

### 3. Diagnostic Tool (diagnose_profit_taking.py)
- Shows which positions are tracked vs untracked
- Calculates P&L for tracked positions
- Identifies positions at profit targets or stop losses
- Shows current RSI and market conditions
- Provides specific recommendations for fixes

## How to Use

### Step 1: Diagnose Current State
```bash
python diagnose_profit_taking.py
```

This will show:
- Which positions are tracked (have entry prices)
- Which positions are untracked (no profit-taking)
- Current P&L for all positions
- Which positions should exit based on targets

### Step 2: Import Untracked Positions
```bash
python import_current_positions.py
```

**IMPORTANT**: This records current prices as entry prices, meaning:
- Future P&L is calculated from TODAY's prices
- Past gains/losses are not tracked
- Positions currently at a loss will show as break-even going forward
- This is intentional - we're starting fresh with profit-taking from now

### Step 3: Restart Bot
```bash
# On Railway/Render, trigger a redeploy
# Or locally:
bash start.sh
```

The bot will now:
1. Track all positions with entry prices
2. Exit positions at profit targets: 2%, 2.5%, 3%, 4%, 5%
3. Exit positions at stop loss: -2%
4. Use enhanced fallback exits (momentum reversal, downtrends)

## Profit Target Strategy

### With Entry Prices (Tracked Positions)
Exits at stepped profit targets after Coinbase fees (~1.4%):
- **+5.0%** gross → ~3.6% NET (EXCELLENT)
- **+4.0%** gross → ~2.6% NET (GREAT)  
- **+3.0%** gross → ~1.6% NET (GOOD)
- **+2.5%** gross → ~1.1% NET (SOLID)
- **+2.0%** gross → ~0.6% NET (PROFITABLE)

Stop loss at **-2.0%** gross → ~-3.4% NET

### Without Entry Prices (Untracked Positions - Fallback)
Uses technical indicators for exits:
- **RSI > 70**: Overbought - lock in gains
- **RSI > 60 + price < EMA9**: Momentum reversal - lock in gains
- **RSI < 30**: Oversold - cut losses
- **RSI < 40 + price < EMA21**: Downtrend - cut losses
- **Market filter fails**: Weak conditions - exit to protect capital

## Monitoring

### Check Bot Logs
Look for these key messages:

**Good signs (profit-taking working):**
```
💰 P&L: +$2.35 (+3.15%) | Entry: $0.22
🎯 PROFIT TARGET HIT: BAT-USD at +3.15% (target: +3.0%)
✅ BAT-USD SOLD successfully!
```

**Warning signs (missing entry prices):**
```
⚠️ No entry price tracked for XLM-USD - using fallback exit logic
💡 Run import_current_positions.py to track this position
```

**Fallback exits working:**
```
📉 MOMENTUM REVERSAL EXIT: SOL-USD (RSI=62.3, price below EMA9)
📉 DOWNTREND EXIT: ETH-USD (RSI=38.5, price below EMA21)
```

### Re-run Diagnostics Periodically
```bash
python diagnose_profit_taking.py
```

This helps catch any new positions that aren't being tracked.

## Expected Behavior Changes

### Before Fix
- Positions accumulate losses with no automatic exits
- Only exit when RSI hits extreme levels (>70 or <30)
- No profit-taking at reasonable gain levels
- Portfolio bleeds slowly during market volatility

### After Fix
- Positions exit at 2%+ profits (after fees = ~0.6%+ NET)
- Positions exit at -2% losses (controlled risk)
- Momentum reversals trigger earlier exits (lock gains before they disappear)
- Downtrends trigger earlier exits (cut losses before they grow)
- Portfolio protection through active position management

## Files Changed

1. **bot/trading_strategy.py**
   - Enhanced momentum-based profit-taking (RSI>60 + weak momentum)
   - Enhanced downtrend loss-cutting (RSI<40 + downtrend)
   - Better logging for untracked positions
   - More granular profit targets (added 5% target)

2. **import_current_positions.py** (NEW)
   - Import tool to track existing positions
   - Interactive with safety prompts
   - Handles position tracker initialization

3. **diagnose_profit_taking.py** (NEW)
   - Diagnostic tool to check profit-taking system health
   - Shows tracked vs untracked positions
   - Identifies positions at exit thresholds
   - Provides specific fix recommendations

## FAQ

**Q: Will importing positions reset my P&L to zero?**
A: Yes, when you import positions using current prices, the P&L resets. Going forward, profit/loss is calculated from the imported prices. This is intentional - it allows profit-taking to work on existing positions.

**Q: What if I don't want to import a position?**
A: The import script is interactive and asks before importing each position. You can choose to skip positions. However, skipped positions will only have the fallback exit logic (RSI/momentum), not profit-taking.

**Q: Why use current price as entry price instead of actual entry price?**
A: Coinbase API doesn't provide entry prices for existing positions. We have two choices:
1. Use current price (profit-taking from now forward)
2. Leave untracked (only RSI/momentum exits, no profit targets)

Option 1 is better - it enables profit-taking even if past performance is lost.

**Q: Will the bot automatically import new positions?**
A: Yes! When the bot places new buy orders, it automatically tracks them with the correct entry price. The import tool is only needed for positions that existed before the tracker was added.

**Q: What if I manually add positions outside the bot?**
A: Run the import tool again to track them, or wait for the fallback exit logic to handle them (less optimal).

## Rollback Instructions

If you need to rollback these changes:

```bash
# Restore original trading_strategy.py
git checkout HEAD~1 bot/trading_strategy.py

# Remove new scripts
rm import_current_positions.py diagnose_profit_taking.py

# Restart bot
bash start.sh
```

**WARNING**: Rolling back disables the enhanced profit-taking. Only do this if issues arise.

## Next Steps

1. ✅ Run diagnostics to see current state
2. ✅ Import untracked positions 
3. ✅ Restart bot to enable enhanced profit-taking
4. 📊 Monitor logs for 24-48 hours
5. 📈 Check if positions are exiting at profit targets
6. 🔧 Adjust profit targets if needed (edit PROFIT_TARGETS in trading_strategy.py)

## Support

If profit-taking still isn't working after following these steps:

1. Check bot logs for error messages
2. Run `diagnose_profit_taking.py` to see system status
3. Verify position tracker file exists: `ls -la bot/positions.json`
4. Check if positions are being tracked on new buys
5. Look for "PROFIT TARGET HIT" messages in logs

The enhanced fallback logic should at minimum catch momentum reversals and downtrends even without entry prices.
