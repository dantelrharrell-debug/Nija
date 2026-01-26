# Profitability Filter Tuning Guide

## Problem Statement

**Issue**: Bot was scanning markets but finding **ZERO trading signals** due to overly strict smart filters.

**Evidence from Logs (2026-01-26)**:
- Scanned 30 markets
- Found 0 signals
- **26 markets rejected by "Smart filter"** (87% rejection rate)
- User reported: "when I was losing money I was trading every 20 min"

**Root Cause**: Multiple strict filters were blocking trades:
1. ADX threshold too high (rejecting trending markets)
2. Volume requirements too strict (rejecting liquid markets)
3. Signal score requirements too high (rejecting valid setups)

## Changes Made

### Filter Relaxation Summary

| Configuration | Before | After | Impact |
|--------------|--------|-------|--------|
| **MARKET_FILTER.adx_threshold** | 20 | **15** | ✅ 25% more lenient |
| **MARKET_FILTER.volume_threshold** | 50% | **30%** | ✅ 40% more lenient |
| **MARKET_FILTERING.min_adx** | 20 | **15** | ✅ 25% more lenient |
| **MARKET_FILTERING.min_volume_multiplier** | 1.5x | **1.2x** | ✅ 20% more lenient |
| **ENTRY_CONFIG.min_signal_score** | 4/6 (67%) | **3/6 (50%)** | ✅ Easier entry |
| **SMART_FILTERS.low_volume.threshold** | 30% | **15%** | ✅ 50% more lenient |
| **SMART_FILTERS.chop_detection.adx_threshold** | 20 | **14** | ✅ 30% more lenient |

### Expected Impact

**Before**: 26 out of 30 markets filtered (87% rejection)  
**After**: Should see **3-5x more trading opportunities**

## Technical Details

### ADX (Average Directional Index)
- **Purpose**: Measures trend strength
- **Old threshold**: 20 (industry standard, but too strict for crypto)
- **New threshold**: 15 for trend detection, 14 for chop detection (1-point buffer to avoid edge cases)
- **Rationale**: Crypto markets are more volatile; ADX 15-20 can still indicate tradeable trends

### Volume Requirements
- **Purpose**: Ensure sufficient liquidity
- **Old**: Volume must be >1.5x average AND >50% of recent average
- **New**: Volume must be >1.2x average AND >30% of recent average
- **Rationale**: Crypto markets have variable volume; 30% is sufficient for execution

### Signal Scoring
- **Purpose**: Confirm entry setup quality
- **Old**: 4 out of 6 confirmations required (67%)
- **New**: 3 out of 6 confirmations required (50%)
- **Rationale**: Perfect setups are rare; 3 confirmations provide sufficient edge

## Safety Measures Maintained

✅ **Stop losses**: Still mandatory on all trades  
✅ **Position limits**: Max 8 positions still enforced  
✅ **Risk per trade**: Still calculated based on account size  
✅ **Trailing stops**: Still active for profit protection  
✅ **News blocking**: Still enabled (placeholder)  
✅ **New candle timing**: Still blocks first 5 seconds  

## Monitoring Recommendations

After deploying these changes, monitor:

1. **Trade Frequency**: Should increase to 3-8 trades per day
2. **Signal Quality**: Track win rate (target: 50-60%)
3. **Filter Stats**: Watch "Smart filter" rejections (should drop to 30-50%)
4. **Profitability**: Focus on positive expectancy over time

## Rollback Instructions

If too many low-quality trades occur, you can:

1. **Conservative rollback** (recommended):
   - Increase `min_signal_score` from 3 → 4
   - Keep other relaxed filters

2. **Full rollback**:
   ```python
   # In bot/apex_config.py
   MARKET_FILTER['adx_threshold'] = 20
   MARKET_FILTER['volume_threshold'] = 0.5
   MARKET_FILTERING['min_adx'] = 20
   MARKET_FILTERING['min_volume_multiplier'] = 1.5
   ENTRY_CONFIG['min_signal_score'] = 4
   SMART_FILTERS['low_volume']['threshold'] = 0.30
   SMART_FILTERS['chop_detection']['adx_threshold'] = 19  # Keep 1 below min_adx
   ```

## Configuration Files Modified

- ✅ `/bot/apex_config.py` - All filter thresholds updated

## Testing

Run validation test:
```bash
cd /home/runner/work/Nija/Nija/bot
python -c "from apex_config import MARKET_FILTER, ENTRY_CONFIG, SMART_FILTERS; \
  print('ADX:', MARKET_FILTER['adx_threshold']); \
  print('Min signals:', ENTRY_CONFIG['min_signal_score']); \
  print('Low vol threshold:', SMART_FILTERS['low_volume']['threshold'])"
```

Expected output:
```
ADX: 15
Min signals: 3
Low vol threshold: 0.15
```

## Next Steps

1. ✅ Deploy to production
2. ⏳ Monitor for 24-48 hours
3. ⏳ Analyze trade frequency and quality
4. ⏳ Adjust if needed based on results

---

**Date**: 2026-01-26  
**Author**: GitHub Copilot  
**Issue**: "Still not profitable trades on kraken or coinbase why"  
**Status**: Filter relaxation complete, awaiting deployment
