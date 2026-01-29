# Trade Size Tuning Guide

## Overview

This guide explains the new trade sizing safety features implemented to increase trade size safely while maintaining profitability.

## Changes Implemented (Jan 20, 2026)

### Option A: Minimum Position Size ($5.00)

**What it does:**
- Blocks trades smaller than $5.00 from executing
- Prevents micro-trades that lose money to fees (~1.4% round-trip on Coinbase)
- Ensures every trade has a realistic chance of being profitable

**Where it's configured:**
- `bot/position_sizer.py`: `MIN_POSITION_USD = 5.0`
- `bot/trading_strategy.py`: `MIN_POSITION_SIZE_USD = 5.0`
- `bot/nija_apex_strategy_v71.py`: Uses `MIN_POSITION_USD` for validation

**How it works:**
```python
# Before executing a trade, the bot checks:
if position_size < MIN_POSITION_USD:
    skip_trade("Position too small: $X.XX < $5.00 minimum")
```

**Benefits:**
- ✅ Prevents unprofitable micro-trades
- ✅ Improves overall profitability by focusing on larger positions
- ✅ Reduces wasted fees on trades too small to profit
- ✅ Better use of account balance

### Option B: Confidence Threshold (0.60)

**What it does:**
- Requires minimum 60% confidence score to execute a trade
- Filters out weak entry signals that are more likely to lose
- Only trades high-quality setups with strong conviction

**Where it's configured:**
- `bot/nija_apex_strategy_v71.py`: `MIN_CONFIDENCE = 0.60`

**How it works:**
```python
# Calculate confidence from entry signal quality (0-1 range)
confidence = min(score / 5.0, 1.0)  # Normalize score to 0-1

# Check confidence threshold
if confidence < MIN_CONFIDENCE:
    skip_trade("Confidence too low: 0.XX < 0.60")
```

**Benefits:**
- ✅ Filters out marginal setups
- ✅ Improves win rate by only trading high-probability entries
- ✅ Reduces losing trades from weak signals
- ✅ Better risk/reward ratio

## Configuration Options

### Adjusting Minimum Position Size

To change the minimum position size, edit these constants:

**File: `bot/position_sizer.py`**
```python
MIN_POSITION_USD = 5.0  # Change to your desired minimum (e.g., 10.0 for $10)
```

**File: `bot/trading_strategy.py`**
```python
MIN_POSITION_SIZE_USD = 5.0  # Keep in sync with position_sizer.py
MIN_BALANCE_TO_TRADE_USD = 5.0  # Keep >= MIN_POSITION_SIZE_USD
```

**Recommendations by account size:**
- **$50-100**: Keep at $5.00 minimum
- **$100-500**: Consider $10.00 minimum
- **$500-1000**: Consider $15-20 minimum
- **$1000+**: Consider $25-50 minimum

### Adjusting Confidence Threshold

To change the confidence threshold, edit:

**File: `bot/nija_apex_strategy_v71.py`**
```python
MIN_CONFIDENCE = 0.60  # Change to your desired threshold (0.0-1.0)
```

**Recommendations:**
- **0.50**: More trades, lower quality (aggressive)
- **0.60**: Balanced (recommended default)
- **0.70**: Fewer trades, higher quality (conservative)
- **0.80**: Very selective, premium setups only

## Monitoring and Logging

### Log Messages to Watch For

**Trade Skipped (Position Too Small):**
```
⏭️  Skipping trade: Position $3.50 below minimum $5.00
```
**Action:** Consider funding account with more capital for better trading

**Trade Skipped (Confidence Too Low):**
```
⏭️  Skipping trade: Confidence 0.45 below minimum 0.60
```
**Action:** Normal - bot is filtering weak entries

**Trade Approved:**
```
✅ Trade approved: Size=$25.00, Confidence=0.75
```
**Action:** Good - trade meets both criteria

## Impact on Trading

### Before These Changes
- ❌ Bot could take $1-2 positions that lose money to fees
- ❌ Bot could enter weak setups with low probability
- ❌ Many small losing trades eating into profits
- ❌ Poor overall profitability on small accounts

### After These Changes
- ✅ Minimum $5.00 position size ensures trades can be profitable
- ✅ 60% confidence threshold filters weak entries
- ✅ Fewer but higher-quality trades
- ✅ Better overall profitability
- ✅ Clear feedback on why trades are skipped

## Examples

### Example 1: Small Account ($50 balance)

**Scenario:** Bot calculates $3.50 position size based on account balance

**Before:** Would execute trade, likely lose money to fees
**After:** Trade skipped with log:
```
⏭️  Skipping trade: Position $3.50 below minimum $5.00
Reason: Position too small (increase account size for better trading)
```

**Action:** Fund account to $75+ for consistent $5+ position sizes

### Example 2: Weak Entry Signal

**Scenario:** Market shows uptrend but entry signal is marginal (score: 2/5 = 0.40 confidence)

**Before:** Would execute trade, higher chance of loss
**After:** Trade skipped with log:
```
⏭️  Skipping trade: Confidence 0.40 below minimum 0.60
Reason: Confidence too low (weak entry signal)
```

**Action:** None needed - bot is working correctly

### Example 3: High-Quality Trade

**Scenario:** Strong uptrend, excellent entry signal (score: 4/5 = 0.80 confidence), $25 position size

**Before:** Would execute trade
**After:** Trade executes with confirmation log:
```
✅ Trade approved: Size=$25.00, Confidence=0.80
```

**Action:** Monitor trade as normal

## Troubleshooting

### Problem: No trades executing

**Possible causes:**
1. Account balance too small for $5 minimum positions
2. Confidence threshold too high (all signals filtered)
3. Market conditions not meeting entry criteria

**Solutions:**
1. Fund account to $50+ minimum for consistent trading
2. Lower MIN_CONFIDENCE to 0.50 if too restrictive
3. Wait for better market conditions

### Problem: Too many trades skipped for size

**Cause:** Account balance too small relative to position sizing logic

**Solution:**
- Fund account to at least $50-100 for $5+ positions
- Or temporarily lower MIN_POSITION_USD to $3.00 (not recommended - less profitable)

### Problem: Too many trades skipped for confidence

**Cause:** MIN_CONFIDENCE threshold too high for current market

**Solution:**
- Lower MIN_CONFIDENCE to 0.50-0.55 for more trades
- Or wait for stronger market conditions with clearer signals

## Safety Features

✅ **All existing risk management preserved**
- Stop losses still enforced
- Position limits still active
- Risk management unchanged

✅ **Additive validation only**
- New checks added, none removed
- Bot is safer than before

✅ **Clear logging and feedback**
- Every skipped trade logged with reason
- Easy to diagnose issues

✅ **No impact on exits**
- Exit logic unchanged
- Trailing stops unchanged
- Profit targets unchanged

## Recommendations for Best Results

1. **Account Size**: Minimum $50-100 for optimal results with $5 minimum positions
2. **Confidence Threshold**: Start with 0.60, adjust after observing results
3. **Monitor Logs**: Watch for patterns in skipped trades
4. **Gradual Adjustments**: Make small changes and observe impact
5. **Quality Over Quantity**: Fewer high-quality trades beat many low-quality trades

## Version History

- **Jan 20, 2026**: Initial implementation
  - MIN_POSITION_USD increased from $1.00 to $5.00
  - MIN_CONFIDENCE threshold added at 0.60
  - Applied to both long and short entries
  - Clear logging for all trade decisions

---

**Questions?** Check logs for detailed feedback on every trade decision.
