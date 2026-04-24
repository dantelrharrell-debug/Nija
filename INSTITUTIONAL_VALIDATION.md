# Institutional Validation Framework

## Overview

NIJA was built out of sequence. The correct institutional order of operations is:

1. **Alpha Discovery** ✅ (now implemented)
2. **Robust Statistical Validation** ✅ (now implemented)
3. **Regime Testing** ✅ (now implemented)
4. **Monte Carlo Stress Testing** ✅ (now implemented)
5. **Capital Scaling Architecture** ✅ (already existed)
6. **Risk Throttles** ✅ (already existed)

This framework provides steps 1-4 that must be proven **BEFORE** activating the existing capital scaling and risk management infrastructure.

## Philosophy

> **If Sharpe < 1 after realistic costs, you don't scale.**

Real funds don't deploy capital until edge is mathematically proven. This framework enforces that discipline.

## Quick Start

### Validate Your Strategy

```bash
# Run simulation to test the framework
python prove_edge.py --simulate --num-trades 500

# Validate from real trade history
python prove_edge.py --trades trade_history.csv

# Generate HTML report
python prove_edge.py --trades trade_history.csv --report edge_report.html
```

### Trade History CSV Format

Your `trade_history.csv` should have these columns:

```csv
return_pct,pnl,regime
2.5,250.00,bull
-1.2,-120.00,bear
3.1,310.00,sideways
```

- `return_pct`: Trade return as percentage (e.g., 2.5 for 2.5%)
- `pnl`: Trade P&L in dollars
- `regime`: Market regime (`bull`, `bear`, or `sideways`)

## The 4-Step Validation Process

### Step 1: Alpha Discovery

**Question:** Does raw edge exist?

**Requirements:**
- Win rate > 50% OR profit factor > 1.5
- Positive expectancy
- Total return > 0

**Why it matters:** If there's no raw alpha, nothing else matters.

### Step 2: Statistical Validation

**Question:** Is it statistically significant after costs?

**Requirements:**
- Sharpe ratio ≥ 1.0 after realistic costs (**institutional minimum**)
- Positive Sortino ratio (handles downside properly)
- p-value < 0.05 (statistically significant)
- Net return > 0 after costs

**Cost Model:**
- Base slippage: 5 bps (0.05%)
- Maker fee: 10 bps (0.10%)
- Taker fee: 20 bps (0.20%)
- Spread: 5 bps (0.05%)
- **Total round-trip cost: ~35-70 bps (0.35-0.70%)**

**Why it matters:** Paper profits without realistic costs are meaningless.

### Step 3: Regime Testing

**Question:** Does it work in all market conditions?

**Requirements:**
- Positive Sharpe in ALL regimes (bull/bear/sideways)
- Minimum 30 trades per regime
- Worst regime Sharpe ≥ 0.5

**Why it matters:** Strategies that only work in one regime fail during transitions.

### Step 4: Monte Carlo Stress Testing

**Question:** Does it survive adverse scenarios?

**Requirements:**
- Probability of ruin < 5%
- Probability of 10% loss < 20%
- Worst drawdown > -30%
- 5th percentile positive (even bad luck is survivable)

**Why it matters:** Markets stress-test strategies. You should too.

## What Happens If Validation Fails?

### ❌ If edge is NOT proven:

```
DO NOT SCALE CAPITAL
```

You should:
1. Improve the strategy
2. Collect more data
3. Re-run validation
4. Only activate capital scaling when ALL 4 steps pass

### ✅ If edge IS proven:

```
READY FOR CAPITAL SCALING
```

You may now:
1. Activate the capital scaling architecture (already built)
2. Enable risk throttles (already built)
3. Deploy capital with confidence

## Using the CLI Tool

### Basic Usage

```bash
# Test with simulation (good for testing the framework)
python prove_edge.py --simulate

# Validate real trading history
python prove_edge.py --trades my_trades.csv

# Generate detailed HTML report
python prove_edge.py --trades my_trades.csv --report validation_report.html
```

### Advanced Options

```bash
# Simulate with custom parameters
python prove_edge.py --simulate \
  --num-trades 1000 \
  --win-rate 0.60 \
  --avg-win 3.0 \
  --avg-loss 1.5

# Specify initial capital for analysis
python prove_edge.py --trades my_trades.csv --initial-capital 250000

# Verbose logging
python prove_edge.py --trades my_trades.csv --verbose
```

## Integration with Trading System

### Entry Discipline Gate

Once edge is proven, the entry discipline framework enforces hard criteria:

```python
from bot.institutional_entry_discipline import (
    InstitutionalEntryDiscipline,
    SignalQuality,
    HardEntryCriteria
)

# Initialize entry discipline
criteria = HardEntryCriteria(
    min_signal_strength=0.65,      # 65% minimum signal strength
    min_risk_reward_ratio=1.5,     # 1.5:1 R:R minimum
    allowed_regimes=['bull', 'sideways']  # Don't trade in bear markets
)

discipline = InstitutionalEntryDiscipline(criteria)

# Evaluate entry signal
signal = SignalQuality(
    signal_strength=0.75,
    num_confirming_indicators=3,
    risk_reward_ratio=2.0,
    stop_distance_pct=0.02,
    current_regime='bull',
    volatility_pct=0.015,
    liquidity_usd=500000,
    spread_pct=0.001,
    max_correlation=0.3,
    hours_since_news=6.0
)

evaluation = discipline.evaluate_entry('BTC-USD', signal)

if evaluation.decision == EntryDecision.APPROVED:
    # Execute trade
    pass
else:
    # Log rejection reasons
    for reason in evaluation.rejection_reasons:
        print(f"Rejected: {reason}")
```

### Key Integration Points

1. **Pre-deployment validation** - Run `prove_edge.py` before going live
2. **Entry gating** - Every entry must pass `InstitutionalEntryDiscipline`
3. **Audit trail** - All decisions are logged for regulatory compliance
4. **No overrides** - Hard criteria cannot be bypassed

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Trading System Flow                       │
└─────────────────────────────────────────────────────────────┘

1. PROVE EDGE (Before deployment)
   ├── Alpha Discovery
   ├── Statistical Validation
   ├── Regime Testing
   └── Monte Carlo Stress
         │
         ▼
   ┌─────────────────┐
   │ Edge Proven?    │
   └────────┬────────┘
            │
      ┌─────┴─────┐
      │           │
     YES         NO
      │           │
      ▼           ▼
   Deploy    Don't Scale
   Capital   (Fix Strategy)

2. LOCK ENTRY DISCIPLINE (Live trading)
   │
   ├── Signal arrives
   │
   ├── InstitutionalEntryDiscipline.evaluate_entry()
   │   ├── Check hard criteria
   │   ├── Check regime filter
   │   ├── Check risk/reward
   │   ├── Check market conditions
   │   └── Check correlations
   │
   ├── Decision: APPROVED or REJECTED
   │
   └── If APPROVED:
       ├── Capital Scaling Architecture (already built)
       └── Risk Throttles (already built)
```

## Files

- **`bot/alpha_validation_framework.py`** - 4-step validation framework
- **`bot/institutional_edge_validator.py`** - Edge validation with slippage modeling
- **`bot/institutional_entry_discipline.py`** - Hard entry criteria enforcement
- **`prove_edge.py`** - CLI tool for operators

## Example Output

```
================================================================================
ALPHA VALIDATION RESULT
================================================================================
Status: PROVEN
Ready for Capital Scaling: ✅ YES

[1/4] Alpha Discovery: ✅ PASS
      Win Rate: 57.2%
      Profit Factor: 2.14
      Expectancy: $125.50

[2/4] Statistical Validation: ✅ PASS
      Sharpe (after costs): 1.235
      Sortino: 1.687
      p-value: 0.0023

[3/4] Regime Testing: ✅ PASS
      Bull Sharpe: 1.45 (180 trades)
      Bear Sharpe: 0.82 (95 trades)
      Sideways Sharpe: 1.12 (225 trades)

[4/4] Monte Carlo Stress: ✅ PASS
      Probability of Ruin: 2.3%
      5th Percentile Return: -4.2%
      Worst Drawdown: -18.5%

✅ ALL 4 STEPS PASSED - READY FOR CAPITAL SCALING
================================================================================
```

## Best Practices

### 1. Run Validation Regularly

```bash
# Monthly validation check
python prove_edge.py --trades last_30_days.csv --report monthly_validation.html
```

### 2. Compare In-Sample vs Out-of-Sample

Split your data:
- First 70% = training/optimization
- Last 30% = validation

If out-of-sample Sharpe < 70% of in-sample, you're overfit.

### 3. Test Across Market Regimes

Ensure you have sufficient trades in each regime:
- Bull market: 30+ trades
- Bear market: 30+ trades
- Sideways market: 30+ trades

### 4. Monitor Entry Discipline

```python
# Check statistics periodically
discipline.log_statistics()
```

Output:
```
====================================================================================================
ENTRY DISCIPLINE STATISTICS
============================================================
Total Evaluations: 1,250
Approved: 187 (15.0%)
Rejected: 1,063

Rejection Breakdown:
  rejected_regime: 456 (42.9%)
  rejected_signal: 312 (29.3%)
  rejected_volatility: 187 (17.6%)
  rejected_liquidity: 108 (10.2%)
============================================================
```

**Key insight:** If approval rate is too high (>30%), criteria may be too loose.

## Frequently Asked Questions

### Q: What if my Sharpe is 0.8?

**A:** Don't scale capital. Either:
- Improve the strategy
- Reduce costs (better execution)
- Wait for more data

**Never scale a strategy with Sharpe < 1.0 after costs.**

### Q: Can I override the hard criteria in special cases?

**A:** No. That defeats the purpose of institutional discipline. If criteria are wrong, change them for all future trades, not just one.

### Q: How often should I re-validate?

**A:** 
- Monthly: Quick check with `prove_edge.py`
- Quarterly: Full analysis with regime segmentation
- After any strategy changes: Mandatory re-validation

### Q: What if I don't have regime labels?

**A:** The framework will use 'sideways' for all trades. However, you should:
1. Add regime classification (see `bot/market_regime_detector.py`)
2. Re-run validation with proper labels

### Q: My strategy worked in backtest but fails validation?

**A:** Common causes:
- Insufficient transaction cost modeling in backtest
- Overfit to specific market regime
- Too few trades for statistical significance
- Selection bias in test data

Fix the backtest, don't bypass validation.

## Next Steps

1. **Run validation on existing trades:**
   ```bash
   python prove_edge.py --trades historical_trades.csv --report validation.html
   ```

2. **If edge is proven:** Activate capital scaling with confidence

3. **If edge is not proven:** Improve strategy before deploying capital

4. **Integrate entry discipline:** Add to trading_strategy.py (see ENTRY_DISCIPLINE_GUIDE.md)

5. **Monitor continuously:** Re-run validation monthly

## Support

For questions or issues:
- Check existing documentation in /docs
- Review test files in /bot/test_*.py
- See example integrations in /examples

## License

See LICENSE file in repository root.
