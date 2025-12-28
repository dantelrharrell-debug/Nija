# QUALITY FIX: Tighter Entry Criteria to Reduce Losing Trades

**Date**: December 28, 2025  
**Issue**: Bot buying too many losing trades (48% win rate, 52% losing)  
**Root Cause**: Entry filters too permissive (3/5 scoring)  
**Solution**: Tighten to 4/5 scoring to filter marginal setups  

---

## Problem Analysis

### Current Performance (Pre-Fix)
- **Total Trades**: 25 completed trades
- **Win Rate**: 48% (12 wins, 13 losses)
- **Loss Rate**: 52%
- **Average Losses**: -2% to -6% (larger than typical wins)

### Recent Losing Trades
```
BTC-USD:   Buy $100.78 → Sell $99.88  = -0.90%
ICP-USD:   Buy $105.07 → Sell $100.45 = -4.40%
FET-USD:   Buy $96.52  → Sell $92.04  = -4.64%
ETH-USD:   Buy $102.42 → Sell $99.40  = -2.95%
FLOW-USD:  Buy $102.04 → Sell $95.86  = -6.06%
BTC-USD:   Buy $99.88  → Sell $94.28  = -5.61%
1INCH-USD: Buy $101.66 → Sell $101.43 = -0.22%
FIL-USD:   Buy $100.22 → Sell $95.78  = -4.43%
ETH-USD:   Buy $96.23  → Sell $93.32  = -3.02%
ETH-USD:   Buy $4000.00 → Sell $3920.00 = -2.00%
```

### Root Cause
The strategy uses a 5-point scoring system for:
1. **Market Filter** (trend confirmation)
2. **Entry Signals** (timing confirmation)

**Previous threshold**: 3/5 (60% confidence)
- Allowed trades when only 60% of conditions were met
- Marginal setups with weak confirmation led to losses

---

## Solution: Tighter Entry Criteria

### Changes Made

#### 1. Market Filter (bot/nija_apex_strategy_v71.py)
**Before**: Required 3/5 conditions for trend confirmation
**After**: Requires 4/5 conditions for trend confirmation

```python
# OLD (3/5 - too permissive)
if uptrend_score >= 3:
    return True, 'uptrend', ...
elif downtrend_score >= 3:
    return True, 'downtrend', ...

# NEW (4/5 - stricter)
if uptrend_score >= 4:
    return True, 'uptrend', ...
elif downtrend_score >= 4:
    return True, 'downtrend', ...
```

**Market Filter Conditions** (need 4/5):
1. VWAP alignment (price above for uptrend)
2. EMA sequence (9 > 21 > 50 for uptrend)
3. MACD histogram positive
4. ADX > 20 (strong trend)
5. Volume > 50% of 5-candle average

#### 2. Long Entry Signal (bot/nija_apex_strategy_v71.py)
**Before**: Required 3/5 conditions for entry
**After**: Requires 4/5 conditions for entry

```python
# OLD (3/5 - too permissive)
signal = score >= 3

# NEW (4/5 - stricter)
signal = score >= 4
```

**Long Entry Conditions** (need 4/5):
1. Pullback to EMA21 or VWAP (within 1%)
2. RSI bullish pullback (30-70 range, recovering)
3. Bullish candlestick pattern (engulfing/hammer)
4. MACD histogram ticking up
5. Volume >= 60% of last 2 candles

#### 3. Short Entry Signal (bot/nija_apex_strategy_v71.py)
**Before**: Required 3/5 conditions for entry
**After**: Requires 4/5 conditions for entry

```python
# OLD (3/5 - too permissive)
signal = score >= 3

# NEW (4/5 - stricter)
signal = score >= 4
```

**Short Entry Conditions** (need 4/5):
1. Pullback to EMA21 or VWAP (within 1%)
2. RSI bearish pullback (30-70 range, declining)
3. Bearish candlestick pattern (engulfing/shooting star)
4. MACD histogram ticking down
5. Volume >= 60% of last 2 candles

#### 4. Config Update (bot/fee_aware_config.py)
Updated MIN_SIGNAL_STRENGTH from 3 to 4:

```python
# OLD
MIN_SIGNAL_STRENGTH = 3  # 60% confidence

# NEW  
MIN_SIGNAL_STRENGTH = 4  # 80% confidence
```

---

## Expected Impact

### Positive Effects
1. **Higher Win Rate**: Filter out marginal setups → expect 55-65% win rate
2. **Fewer Losing Trades**: Only trade when 80% of conditions align
3. **Better Risk/Reward**: High-probability setups have better R:R
4. **Improved Profitability**: Fewer losses × higher win rate = net positive

### Trade-offs
1. **Fewer Trades**: Stricter filters = fewer opportunities
   - **Before**: ~25 trades (with 3/5 scoring)
   - **After**: ~15-20 trades (with 4/5 scoring)
   - **Net Effect**: Better quality over quantity

2. **Slower Capital Growth**: Less frequent trades
   - **Mitigation**: Higher win rate compensates for lower frequency

---

## Verification

### Before Deployment
✅ Syntax validated: All files pass Python AST parsing
✅ Logic verified: Scoring thresholds updated consistently
✅ Config aligned: MIN_SIGNAL_STRENGTH matches strategy code

### After Deployment (Monitor These)
- [ ] Win rate improves to >55%
- [ ] Average loss stays at -2% (stop loss working)
- [ ] Average win increases to +2-3%
- [ ] Daily P&L becomes consistently positive
- [ ] Trade frequency: 15-20 trades instead of 25

---

## Technical Details

### Files Modified
1. `bot/nija_apex_strategy_v71.py`
   - Line 146-149: Market filter uptrend/downtrend (3→4)
   - Line 227: Long entry signal (3→4)
   - Line 308: Short entry signal (3→4)

2. `bot/fee_aware_config.py`
   - Line 97: MIN_SIGNAL_STRENGTH (3→4)

### Scoring Logic
**5-Point System**: Each condition = 1 point

**Old Threshold (3/5)**:
- 60% confidence
- Allows "maybe" trades
- Results: 48% win rate ❌

**New Threshold (4/5)**:
- 80% confidence
- Only "strong" trades
- Expected: 55-65% win rate ✅

---

## Rollback Plan (If Needed)

If win rate doesn't improve within 20 trades:

```bash
# Revert to 3/5 scoring
git revert <commit_hash>
```

**Alternative**: Try 3.5/5 equivalent by requiring:
- Market filter: 4/5 (keep strict)
- Entry signal: 3/5 (loosen)

This would be a middle ground approach.

---

## Conclusion

**Problem**: Too many losing trades (52% loss rate)  
**Cause**: 3/5 scoring too permissive  
**Solution**: Raise to 4/5 scoring (80% confidence)  
**Expected**: Win rate 55-65%, fewer but better trades  

**Status**: ✅ Ready for deployment  
**Risk**: Low - can revert easily if needed  
**Benefit**: High - should significantly reduce losing trades
