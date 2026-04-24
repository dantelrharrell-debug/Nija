# Trade Size Tuning Guide

## Overview

This guide explains the trade sizing safety features and how to tune them for
different account sizes, including the support for **tiny positions** when they
are required.

## Changes Implemented (Mar 2026) – Tiny Position Support

The minimum trade size floor across all configuration files has been lowered
from **$10** to **$1** so that the bot can trade tiny positions whenever they
are required (e.g. very small accounts, dust-sweep operations, or deliberate
micro-allocation strategies).

> ⚠️  **Fee Warning**: Positions under $10 face significant fee pressure
> (~1.4% round-trip on Coinbase).  Raise the minimums back to $10 on
> well-funded accounts for better long-term profitability.

### Files Updated

| File | Constant | Old Value | New Value |
|------|----------|-----------|-----------|
| `bot/trading_strategy.py` | `BASE_MIN_POSITION_SIZE_USD` | $10 | $1 |
| `bot/trading_strategy.py` | `BROKERAGE_MIN_TRADE_USD` (all) | $10 | $1 |
| `bot/trading_strategy.py` | `MIN_BALANCE_TO_TRADE_USD` | $10 | $1 |
| `bot/best_practice_config.py` | `MIN_TRADE_SIZE` | $10 | $1 |
| `bot/best_practice_config.py` | `MIN_BALANCE_REQUIRED` | $75 | $1 |
| `config/__init__.py` | `min_position_size` (default) | $10 | $1 |
| `bot/execution_minimum_position_gate.py` | `TIER_MINIMUM_USD` (all tiers) | $7.50–$100 | $1 |
| `bot/execution_minimum_position_gate.py` | `LOW_CAPITAL_MIN_POSITION` | $7.50 | $1 |

---

## Previous Implementation (Jan 20, 2026)

### Option A: Minimum Position Size ($5.00 → raised to $10.00)

**What it does:**
- Blocks trades smaller than $10.00 from executing
- Prevents micro-trades that lose money to fees (~1.4% round-trip on Coinbase)
- Ensures every trade has a realistic chance of being profitable

**Where it was configured:**
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

**File: `bot/trading_strategy.py`**
```python
BASE_MIN_POSITION_SIZE_USD = 1.0  # $1 – allows tiny positions when required
# Raise to 10.0 for fee-efficient trading on well-funded accounts
```

**File: `bot/best_practice_config.py`**
```python
MIN_TRADE_SIZE = 1.00  # $1 minimum per trade
MIN_BALANCE_REQUIRED = 1.00  # $1 minimum account balance
```

**File: `config/__init__.py`** (UserConfig defaults)
```python
'min_position_size': 1.0,  # $1 – allows tiny positions when required
```

**Recommendations by account size:**
- **< $10**: $1.00 minimum (tiny positions allowed)
- **$10-100**: Consider $2.00–$5.00 minimum
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
⏭️  Skipping trade: Position $0.50 below minimum $1.00
```
**Action:** Fund account or lower the minimum further

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

### With Tiny Position Support (Mar 2026)
- ✅ Minimum $1.00 position size – tiny positions tradeable when required
- ✅ Small accounts (< $10) can participate
- ⚠️  Fee impact is significant on sub-$10 positions (~1.4% round-trip)
- ⚠️  Raise minimums on well-funded accounts for better profitability

## Examples

### Example 1: Tiny Account ($5 balance)

**Scenario:** Bot calculates $0.90 position size based on account balance

**Before (Jan 2026):** Trade skipped (below $10 minimum)
**After (Mar 2026):** Trade executes (above $1 minimum)

**Log:**
```
✅ Trade approved: Size=$0.90, Confidence=0.75
⚠️  Small position – fee impact ~1.4%
```

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
1. Account balance too small for $1 minimum positions
2. Confidence threshold too high (all signals filtered)
3. Market conditions not meeting entry criteria

**Solutions:**
1. Lower MIN_CONFIDENCE to 0.50 if too restrictive
2. Wait for better market conditions

### Problem: Too many trades skipped for size

**Cause:** Account balance extremely small (< $1)

**Solution:**
- Fund account to at least $1 for minimum trading
- Or lower BASE_MIN_POSITION_SIZE_USD further (not recommended)

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

1. **Account Size**: Fund to $50-100+ for optimal fee efficiency with larger positions
2. **Tiny Positions**: Use $1 minimum only when required (dust sweeps, micro-accounts)
3. **Confidence Threshold**: Start with 0.60, adjust after observing results
4. **Monitor Logs**: Watch for patterns in skipped trades and fee impact on tiny positions
5. **Gradual Adjustments**: Make small changes and observe impact
6. **Quality Over Quantity**: Fewer high-quality trades beat many low-quality trades

## Version History

- **Mar 2026**: Tiny position support
  - `BASE_MIN_POSITION_SIZE_USD` lowered from $10 to $1
  - `BROKERAGE_MIN_TRADE_USD` all entries lowered to $1
  - `MIN_BALANCE_TO_TRADE_USD` lowered from $10 to $1
  - `MIN_TRADE_SIZE` in best_practice_config.py lowered to $1
  - `MIN_BALANCE_REQUIRED` in best_practice_config.py lowered to $1
  - `min_position_size` default in config/__init__.py lowered to $1
  - `TIER_MINIMUM_USD` and `LOW_CAPITAL_MIN_POSITION` in execution gate lowered to $1
- **Jan 20, 2026**: Initial implementation
  - MIN_POSITION_USD increased from $1.00 to $5.00 (later to $10)
  - MIN_CONFIDENCE threshold added at 0.60
  - Applied to both long and short entries
  - Clear logging for all trade decisions

---

**Questions?** Check logs for detailed feedback on every trade decision.

