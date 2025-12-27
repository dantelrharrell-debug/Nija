# Quick Fix Guide: Stop Portfolio Bleeding

## TL;DR - Fix in 3 Steps

Your bot isn't taking profits because existing positions don't have entry prices tracked. Here's the quick fix:

### Step 1: Check What's Wrong (30 seconds)
```bash
python diagnose_profit_taking.py
```

This shows which positions are untracked and missing profit-taking.

### Step 2: Fix It (2 minutes)
```bash
python import_current_positions.py
```

**What this does:**
- Records current prices as "entry prices" for all positions
- Enables profit-taking from NOW forward
- Positions will exit at 2%, 2.5%, 3%, 4%, or 5% profit

**Important:** This resets P&L tracking. Past gains/losses are forgotten. Profit-taking starts from current levels.

### Step 3: Restart Bot
On Railway/Render: Trigger a redeploy
The bot will now automatically take profits!

---

## What Changed

### Before This Fix
❌ Positions accumulate losses with no exits
❌ Only exits at extreme RSI (>70 or <30) 
❌ No profit-taking at reasonable levels
❌ Portfolio bleeds during volatility

### After This Fix  
✅ Exits at 2%+ profits (~0.6%+ NET after fees)
✅ Exits at -2% losses (controlled risk)
✅ Momentum reversal exits (RSI>60 + weakness)
✅ Downtrend exits (RSI<40 + downtrend)
✅ Active position management

---

## Expected Results (Next 24-48 Hours)

You should see in bot logs:

```
💰 P&L: +$2.35 (+3.15%) | Entry: $0.22
🎯 PROFIT TARGET HIT: BAT-USD at +3.15% (target: +3.0%)
✅ BAT-USD SOLD successfully!
```

Or for untracked positions (fallback mode):

```
📉 MOMENTUM REVERSAL EXIT: SOL-USD (RSI=62.3, price below EMA9)
✅ SOL-USD SOLD successfully!
```

---

## Still Bleeding After 48 Hours?

1. Run diagnostics again: `python diagnose_profit_taking.py`
2. Check bot logs for "PROFIT TARGET HIT" messages
3. Verify positions.json file exists: `ls -la positions.json`
4. Make sure bot is running (not stopped)
5. Check for STOP_ALL_ENTRIES.conf blocking exits

---

## Technical Details

**Profit Targets** (after ~1.4% Coinbase fees):
- 5% gross → 3.6% NET ⭐⭐⭐
- 4% gross → 2.6% NET ⭐⭐
- 3% gross → 1.6% NET ⭐
- 2.5% gross → 1.1% NET ✓
- 2% gross → 0.6% NET ✓

**Stop Loss**: -2% gross → -3.4% NET

**Fallback Exits** (when entry price unknown):
- RSI > 70: Exit (overbought)
- RSI > 60 + price < EMA9: Exit (momentum reversal)
- RSI < 30: Exit (oversold)
- RSI < 40 + price < EMA21: Exit (downtrend)
- Market filter fails: Exit (weak conditions)

---

## Files in This Fix

- `PROFIT_TAKING_FIX.md` - Complete documentation
- `diagnose_profit_taking.py` - Diagnostic tool
- `import_current_positions.py` - Import tool  
- `bot/trading_strategy.py` - Enhanced with better profit-taking

---

## Questions?

**Q: Will I lose my current P&L tracking?**
A: Yes, importing resets P&L to current prices. This is necessary to enable profit-taking.

**Q: Do I need to import positions manually?**
A: Only once, for existing positions. New positions auto-track on buy.

**Q: What if I don't import positions?**
A: They'll use fallback exits (RSI/momentum only, no profit targets). This is less optimal.

See `PROFIT_TAKING_FIX.md` for full FAQ and details.
