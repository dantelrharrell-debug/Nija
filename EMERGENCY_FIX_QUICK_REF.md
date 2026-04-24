# NIJA Emergency Fix - Quick Reference

## What Changed?
Bot was finding **0 signals** with 28/30 markets filtered. Emergency relaxation of 6 parameters to re-enable trading.

## TL;DR Changes
```python
# bot/nija_apex_strategy_v71.py
min_adx: 12 → 8                    # Allow weaker trends
volume_threshold: 0.2 → 0.1        # 10% of 5-candle avg
volume_min_threshold: 0.02 → 0.005 # 0.5% of 20-candle avg
candle_exclusion: 3s → 1s          # Trade earlier in candles
pullback_tolerance: 1% → 2%        # Wider EMA/VWAP pullback
entry_score: 3/5 → 2/5             # Require fewer conditions
```

## Deploy & Monitor

### Step 1: Deploy (Now)
```bash
# Changes are already committed
git checkout copilot/investigate-nija-plummeting
# Restart bot to apply changes
```

### Step 2: First 6 Hours
**Expected**: 1-3 signals per cycle (vs. current 0)

Watch for:
- ✅ Signal generation increases
- ⚠️ Markets passing filters (expect 5-10 of 30)
- 🚨 Still 0 signals = Need further action

### Step 3: First 24 Hours
**Monitor**: Win rate and trade quality

Alert thresholds:
- 🚨 Win rate < 40% after 20 trades → **IMMEDIATE TIGHTENING**
- ⚠️ Win rate 40-50% → Monitor closely
- 🚨 Still 0-1 signals/cycle → Need more relaxation
- 🚨 Slippage > 1% → Increase volume threshold

### Step 4: Adjust if Needed

**If win rate < 40%** (Quality too low):
```python
# Tighten immediately
self.min_adx = 10                  # Was 8
self.entry_score >= 3              # Was 2/5
self.volume_min_threshold = 0.01   # Was 0.005
```

**If still no signals** (Too strict):
```python
# Further relax
self.candle_exclusion_seconds = 0  # Disable timing filter
self.volume_min_threshold = 0.001  # 0.1% threshold
```

## Risk Controls (Still Active)
- ✅ Stop losses on all positions
- ✅ Position size limits
- ✅ Maximum 8 positions
- ✅ Fee-aware profit targets
- ✅ Stepped profit-taking

## Rollback (If Needed)
```python
# Revert to Jan 27, 2026 settings
self.min_adx = 12
self.volume_threshold = 0.2
self.volume_min_threshold = 0.02
self.candle_exclusion_seconds = 3
# In entry functions:
near_ema21 = abs(current_price - ema21) / ema21 < 0.01
signal = score >= 3
```

## Why So Aggressive?
- Bot had 0 signals despite 2 previous relaxations
- $53.14 balance (down from $77.31) needs active trading
- Current state: No trading = guaranteed loss
- Better to trade with risk than not trade at all
- Can tighten if quality drops

## Success Criteria
1. **Primary**: Generate 1+ signals per cycle ✅ Expected
2. **Secondary**: Maintain >40% win rate ⏳ Monitor
3. **Tertiary**: Recover capital ⏳ Monitor

## Questions?
See full details: `EMERGENCY_FILTER_RELAXATION_JAN_29_2026.md`

---
**Status**: Ready for deployment
**Date**: 2026-01-29
**Priority**: Critical 🔴
