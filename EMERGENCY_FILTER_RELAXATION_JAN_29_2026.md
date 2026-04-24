# Emergency Filter Relaxation - January 29, 2026

## Problem Statement

The NIJA trading bot was losing money and not finding any trading opportunities:
- Balance decreased to $53.14 (down from $77.31 total capital)
- Scanning 30 markets per cycle but finding **0 signals**
- Smart filters rejecting **28/30 markets** (93% rejection rate)
- Logs showed: "📊 Market filter: 0", "🚫 No entry signal: 1", "💵 Position too small: 0"

## Root Cause Analysis

Despite two previous filter relaxations (Jan 26 and Jan 27), the bot's filters remained too restrictive for current market conditions:

1. **Volume Smart Filter**: 2% threshold was filtering out most low-volume crypto markets
2. **Candle Timing Filter**: 3-second exclusion at start of candles was blocking too many opportunities
3. **Entry Signal Requirements**: Required 3/5 conditions, all with strict thresholds
4. **Market Filter ADX**: Threshold of 12 was too high for choppy crypto markets
5. **Pullback Tolerance**: 1% tolerance for EMA21/VWAP was too tight for volatile crypto

## Changes Implemented (Third Relaxation)

### File: `bot/nija_apex_strategy_v71.py`

#### 1. ADX Minimum Threshold
- **Previous**: 12
- **New**: 8
- **Impact**: Allow trading in very weak trends
- **Progression**: 15 → 12 → 8

#### 2. Volume Threshold (Market Filter - 5-candle average)
- **Previous**: 0.2 (20% of average)
- **New**: 0.1 (10% of average)
- **Impact**: Allow trading in lower volume conditions
- **Progression**: 0.3 → 0.2 → 0.1

#### 3. Volume Minimum Threshold (Smart Filter - 20-candle average)
- **Previous**: 0.02 (2% of average)
- **New**: 0.005 (0.5% of average)
- **Impact**: Only filter completely dead markets
- **Progression**: 0.05 → 0.02 → 0.005

#### 4. Candle Exclusion Seconds
- **Previous**: 3 seconds
- **New**: 1 second
- **Impact**: Allow trading earlier in candle formation
- **Progression**: 6 → 3 → 1

#### 5. Pullback Tolerance (EMA21/VWAP)
- **Previous**: 1.0% (0.01)
- **New**: 2.0% (0.02)
- **Impact**: Accept wider pullbacks to support/resistance zones
- **Applies to**: Both long and short entry conditions

#### 6. Entry Signal Score Requirement
- **Previous**: 3/5 conditions required
- **New**: 2/5 conditions required
- **Impact**: Generate signals with fewer confirmations
- **Progression**: 5/5 → 3/5 → 2/5
- **Applies to**: Both long and short entry signals

## Maintained Settings

These settings were already relaxed and remain unchanged:
- **Trend Confirmation**: 2/5 conditions (already relaxed)
- **News Buffer**: 5 minutes (stub - not yet implemented)

## Expected Outcomes

⚠️ **IMPORTANT**: These changes are intentionally aggressive given the current zero-signal situation. The goal is to re-enable trading and then fine-tune based on actual results.

### Positive
1. **Increased Signal Generation**: Bot should find more trading opportunities
2. **Higher Market Participation**: More of the 30 scanned markets should pass filters
3. **Faster Position Building**: With $53.14 balance, need active trading to recover

### Risks to Monitor

⚠️ **Code Review Concerns Acknowledged**:
- **ADX at 8**: Extremely low, indicates weak/random trends - high whipsaw risk
- **Volume at 0.5%**: Very low, may cause slippage and execution issues
- **2/5 Entry Score**: Only 40% of criteria met - significant quality reduction
- **Combined Effect**: All relaxations together create aggressive conditions

**Mitigation Strategy**: Close monitoring with rapid adjustment if quality drops below 40% win rate.
1. **Signal Quality**: Lower entry requirements may reduce trade quality
2. **False Breakouts**: Trading in weaker trends increases risk
3. **Slippage**: Lower volume markets may have higher slippage
4. **Whipsaws**: Weak trends can reverse quickly

## Monitoring Plan

### Key Metrics to Watch
1. **Signal Generation Rate**: Should increase from 0 to at least 1-3 per cycle
2. **Win Rate**: Monitor if it drops below 50%
3. **Average Trade P&L**: Watch for increase in losing trades
4. **Filter Statistics**: Track which markets now pass vs. fail filters

### Adjustment Triggers

**If signal quality is too low** (win rate < 40% after 20+ trades):
- Tighten entry score requirement back to 3/5
- Increase ADX threshold to 10
- Increase volume_min_threshold to 0.01 (1%)

**If still insufficient signals** (0-1 per cycle after 24 hours):
- Consider disabling candle timing filter entirely
- Further reduce volume_min_threshold to 0.001 (0.1%)

**If too many signals with poor quality** (>10 per cycle with losses):
- Add back some selectivity via enhanced scoring weights
- Increase pullback tolerance requirement
- Tighten entry score to 3/5

**Warning level (win rate 40-50%)**:
- Monitor closely but don't adjust yet
- Collect more data (need 30+ trades for statistical significance)

**Critical level (win rate < 40%)**:
- Immediately tighten filters as described above
- Review trade-by-trade to identify issues

## Risk Controls That Remain Active

Even with relaxed filters, these protections are still in place:
1. ✅ Position size limits based on account balance
2. ✅ Stop losses on all positions
3. ✅ Stepped profit-taking system
4. ✅ Maximum position cap (8 positions)
5. ✅ Broker-specific minimum position sizes
6. ✅ Fee-aware profit targets
7. ✅ Trailing stops after TP1 hit

## Code Review Status

- [x] Changes implemented in `bot/nija_apex_strategy_v71.py`
- [x] All parameter updates verified via regex checks
- [x] Documentation updated in function docstrings
- [ ] Live testing in production environment
- [ ] 24-hour performance monitoring
- [ ] Review and fine-tune based on results

## Rollback Plan

If changes prove detrimental (significant losses or poor trade quality):

```python
# Revert to previous values (Jan 27, 2026 settings):
self.min_adx = 12
self.volume_threshold = 0.2
self.volume_min_threshold = 0.02
self.candle_exclusion_seconds = 3
# In entry functions:
near_ema21 = abs(current_price - ema21) / ema21 < 0.01
near_vwap = abs(current_price - vwap) / vwap < 0.01
signal = score >= 3
```

## Next Steps

1. ✅ Deploy changes to production
2. ⏳ Monitor first 6 hours for signal generation
3. ⏳ Analyze quality of first 5-10 trades
4. ⏳ Review 24-hour performance metrics
5. ⏳ Fine-tune based on results

## Historical Context

### First Relaxation (Jan 26, 2026)
- ADX: 15 → 12
- Volume threshold: 0.3 → 0.25
- Entry score: 5/5 → 3/5
- **Result**: Still 0 signals found

### Second Relaxation (Jan 27, 2026)
- Volume threshold: 0.25 → 0.2
- Volume min threshold: 0.05 → 0.02
- Candle exclusion: 6s → 3s
- **Result**: Still 0 signals found (28/30 markets filtered)

### Third Relaxation (Jan 29, 2026) - THIS DOCUMENT
- ADX: 12 → 8
- Volume threshold: 0.2 → 0.1
- Volume min threshold: 0.02 → 0.005
- Candle exclusion: 3s → 1s
- Pullback tolerance: 1% → 2%
- Entry score: 3/5 → 2/5
- **Expected**: Significant increase in signal generation

---

**Date**: January 29, 2026
**Author**: GitHub Copilot
**Status**: Deployed - Monitoring
**Priority**: High - Emergency fix for zero signal generation
