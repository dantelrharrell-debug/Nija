# Module-by-Module Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying each trading enhancement module incrementally with exact diff patches.

**Deployment Strategy:** One module at a time with validation between each step.

---

## Prerequisites

```bash
# Ensure you're on a clean branch
git status
# Should show: nothing to commit, working tree clean

# Create deployment branch
git checkout -b deploy/trading-enhancements

# Verify all tests exist
ls test_*.py
# Should show all test files
```

---

## Module 1: Profitability Assertion Guard (CRITICAL - Deploy First)

### Why First?
This is the **safety net** that prevents unprofitable configurations. Must be deployed before any trading logic changes.

### Files to Add
- `bot/profitability_assertion.py` (434 lines)
- `test_profitability_assertion.py` (323 lines)

### Manual Application

Create `bot/profitability_assertion.py`:
```python
# Copy from the implementation in bot/profitability_assertion.py
# Full file is already in the repository
```

Create `test_profitability_assertion.py`:
```python
# Copy from test_profitability_assertion.py
# Full file is already in the repository
```

### Validation

```bash
# Run tests
python -m unittest test_profitability_assertion -v

# Test with valid config (should pass)
python -c "
from bot.profitability_assertion import assert_strategy_is_profitable
assert_strategy_is_profitable(
    profit_targets=[5.0, 3.5, 2.5, 2.0],
    stop_loss_pct=1.25,
    primary_target_pct=2.5,
    exchange='coinbase'
)
print('✅ Valid config passed')
"

# Test with invalid config (should fail)
python -c "
from bot.profitability_assertion import assert_strategy_is_profitable
try:
    assert_strategy_is_profitable(
        profit_targets=[1.0, 0.8],  # Unprofitable!
        stop_loss_pct=2.0,
        primary_target_pct=1.0,
        exchange='coinbase'
    )
    print('❌ ERROR: Should have failed!')
except Exception as e:
    print('✅ Correctly caught unprofitable config')
"
```

### Commit

```bash
git add bot/profitability_assertion.py test_profitability_assertion.py
git commit -m "Add profitability assertion guard - prevents unprofitable configs"
```

---

## Module 2: Stop-Loss Test Validator (CRITICAL - Deploy Second)

### Why Second?
Ensures all stop-loss logic has tests before allowing deployment.

### Files to Add
- `validate_stop_loss_tests.py` (271 lines)

### Manual Application

Create `validate_stop_loss_tests.py`:
```python
# Copy from validate_stop_loss_tests.py
# Make executable: chmod +x validate_stop_loss_tests.py
```

### Validation

```bash
# Make executable
chmod +x validate_stop_loss_tests.py

# Run validator
python validate_stop_loss_tests.py
# Should scan all stop-loss logic and report status

# Expected output:
# 🛡️ STOP-LOSS TEST VALIDATOR
# Scanning for stop-loss logic without unit tests...
# Found X files with stop-loss logic
# [Either all pass or some need tests]
```

### Commit

```bash
git add validate_stop_loss_tests.py
git commit -m "Add stop-loss test validator - blocks deployment without tests"
```

---

## Module 3: Profitability Audit Report (Deploy Third)

### Why Third?
Provides the monitoring and reporting needed to validate subsequent modules.

### Files to Add
- `profitability_audit_report.py` (373 lines)

### Manual Application

Create `profitability_audit_report.py`:
```python
# Copy from profitability_audit_report.py
# Make executable: chmod +x profitability_audit_report.py
```

### Validation

```bash
# Make executable
chmod +x profitability_audit_report.py

# Run audit (will show no trades initially)
python profitability_audit_report.py --hours 24

# Expected output:
# 🔍 NIJA PROFITABILITY AUDIT REPORT
# Analysis Period: Last 24 hours
# ...
# ⚠️ NO TRADES YET - DEPLOY AND MONITOR
```

### Commit

```bash
git add profitability_audit_report.py
git commit -m "Add profitability audit report - continuous monitoring"
```

---

## Module 4: Feature Flag System (Deploy Fourth)

### Why Fourth?
Enables controlled rollout of remaining features.

### Files to Add
- `bot/feature_flags.py` (119 lines)

### Manual Application

Create `bot/feature_flags.py`:
```python
# Copy from bot/feature_flags.py
```

### Validation

```bash
# Test feature flags
python -c "
from bot.feature_flags import get_feature_flags, FeatureFlag

flags = get_feature_flags()
print('All flags:', flags.get_all_flags())

# Safety features should be locked ON
print('Profitability assertion:', flags.is_enabled(FeatureFlag.PROFITABILITY_ASSERTION))
print('Stop-loss validation:', flags.is_enabled(FeatureFlag.STOP_LOSS_VALIDATION))

# New features should default OFF
print('Entry quality:', flags.is_enabled(FeatureFlag.ENTRY_QUALITY_AUDIT))
"

# Expected output:
# All flags: {...}
# Profitability assertion: True (LOCKED)
# Stop-loss validation: True (LOCKED)
# Entry quality: False
```

### Commit

```bash
git add bot/feature_flags.py
git commit -m "Add feature flag system for controlled rollout"
```

---

## Module 5: Entry Quality Audit (Deploy Fifth)

### Why Fifth?
Lowest risk, highest impact feature. Ready to deploy with feature flag control.

### Files to Add
- `bot/entry_quality_audit.py` (406 lines)
- `test_entry_quality_audit.py` (281 lines)

### Manual Application

Create files from repository.

### Validation

```bash
# Run tests (requires pandas, numpy - may need to install)
python -m unittest test_entry_quality_audit -v

# Test scoring
python -c "
from bot.entry_quality_audit import EntryQualityScorer
import pandas as pd
import numpy as np

# Create sample data
dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
df = pd.DataFrame({
    'open': np.random.uniform(39500, 40500, 100),
    'high': np.random.uniform(40000, 41000, 100),
    'low': np.random.uniform(39000, 40000, 100),
    'close': np.random.uniform(39500, 40500, 100),
    'volume': np.random.uniform(100, 1000, 100)
})
df['high'] = df[['open', 'close', 'high']].max(axis=1)
df['low'] = df[['open', 'close', 'low']].min(axis=1)

scorer = EntryQualityScorer()
audit = scorer.score_entry(
    symbol='BTC-USD',
    df=df,
    signal_type='LONG',
    rsi_9=28,
    rsi_14=32,
    macd_value=100,
    macd_signal=50,
    adx_value=35,
    current_price=40000,
    volume_ratio=2.0,
    stop_distance_pct=2.0,
    target_distance_pct=6.0
)

print(f'Score: {audit[\"total_score\"]}/100')
print(f'Rating: {audit[\"quality_rating\"]}')
print(f'Passed: {audit[\"passed\"]}')
"
```

### Integration

Add to strategy code:
```python
from bot.feature_flags import is_feature_enabled, FeatureFlag
from bot.entry_quality_audit import get_entry_quality_scorer

# In entry logic
if is_feature_enabled(FeatureFlag.ENTRY_QUALITY_AUDIT):
    scorer = get_entry_quality_scorer()
    audit = scorer.score_entry(...)
    
    if not audit['passed']:
        logger.info(f"Entry rejected - quality score: {audit['total_score']}/100")
        return  # Skip this entry
```

### Commit

```bash
git add bot/entry_quality_audit.py test_entry_quality_audit.py
git commit -m "Add entry quality audit system - filters low-quality entries"
```

---

## Module 6: Volatility-Adaptive Sizing (Deploy Sixth)

### Files to Add
- `bot/volatility_adaptive_sizing.py` (353 lines)
- `test_volatility_adaptive_sizing.py` (269 lines)

### Manual Application

Create files from repository.

### Validation

```bash
# Run tests
python -m unittest test_volatility_adaptive_sizing -v

# Test sizing calculation
python -c "
from bot.volatility_adaptive_sizing import VolatilityAdaptiveSizer
import pandas as pd
import numpy as np

# Create sample data
dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
df = pd.DataFrame({
    'open': np.random.uniform(39500, 40500, 100),
    'high': np.random.uniform(40000, 41000, 100),
    'low': np.random.uniform(39000, 40000, 100),
    'close': np.random.uniform(39500, 40500, 100),
    'volume': np.random.uniform(100, 1000, 100)
})
df['high'] = df[['open', 'close', 'high']].max(axis=1)
df['low'] = df[['open', 'close', 'low']].min(axis=1)

sizer = VolatilityAdaptiveSizer()
size, details = sizer.calculate_position_size(
    df=df,
    account_balance=10000,
    current_price=40000
)

print(f'Position size: ${size:.2f}')
print(f'Percentage: {details[\"adjusted_pct\"]*100:.1f}%')
print(f'Volatility: {details[\"volatility_pct\"]:.2f}%')
print(f'Regime: {details[\"volatility_regime\"]}')
"
```

### Integration

```python
from bot.feature_flags import is_feature_enabled, FeatureFlag
from bot.volatility_adaptive_sizing import get_volatility_adaptive_sizer

# In position sizing logic
if is_feature_enabled(FeatureFlag.VOLATILITY_ADAPTIVE_SIZING):
    sizer = get_volatility_adaptive_sizer()
    position_size, details = sizer.calculate_position_size(
        df=ohlcv_data,
        account_balance=balance,
        current_price=price
    )
else:
    # Use fixed sizing
    position_size = balance * 0.05
```

### Commit

```bash
git add bot/volatility_adaptive_sizing.py test_volatility_adaptive_sizing.py
git commit -m "Add volatility-adaptive position sizing"
```

---

## Module 7: Dynamic Stop Manager (Deploy Seventh - CAREFULLY)

### Files to Add
- `bot/dynamic_stop_manager.py` (467 lines)
- `test_dynamic_stop_manager.py` (353 lines)

### Pre-Deployment Check

```bash
# CRITICAL: Run stop-loss test validator
python validate_stop_loss_tests.py

# Must exit 0 (all stop logic has tests)
echo $?  # Should be 0
```

### Manual Application

Create files from repository.

### Validation

```bash
# Run tests
python -m unittest test_dynamic_stop_manager -v

# Test stop calculation
python -c "
from bot.dynamic_stop_manager import DynamicStopManager
import pandas as pd
import numpy as np

# Create trending data
dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
trend = np.linspace(0, 2500, 100)
df = pd.DataFrame({
    'open': 40000 + trend + np.random.uniform(-100, 100, 100),
    'high': 40000 + trend + np.random.uniform(0, 200, 100),
    'low': 40000 + trend - np.random.uniform(0, 200, 100),
    'close': 40000 + trend + np.random.uniform(-100, 100, 100),
    'volume': np.random.uniform(100, 1000, 100)
})
df['high'] = df[['open', 'close', 'high']].max(axis=1)
df['low'] = df[['open', 'close', 'low']].min(axis=1)

manager = DynamicStopManager()
stop_info = manager.calculate_initial_stop(
    position_id='TEST_POS',
    df=df,
    entry_price=40000,
    signal_type='LONG'
)

print(f'Initial stop: ${stop_info[\"stop_price\"]:.2f}')
print(f'Stop distance: {stop_info[\"stop_distance_pct\"]:.2f}%')
print(f'ATR multiplier: {stop_info[\"atr_multiplier\"]}x')
"
```

### Integration

```python
from bot.feature_flags import is_feature_enabled, FeatureFlag
from bot.dynamic_stop_manager import get_dynamic_stop_manager

# In stop management logic
if is_feature_enabled(FeatureFlag.DYNAMIC_STOP_EXPANSION):
    manager = get_dynamic_stop_manager()
    
    # On entry
    stop_info = manager.calculate_initial_stop(
        position_id=position_id,
        df=ohlcv_data,
        entry_price=entry_price,
        signal_type=signal_type
    )
    
    # On update
    updated_stop = manager.update_stop(
        position_id=position_id,
        df=ohlcv_data,
        current_price=current_price
    )
```

### Commit

```bash
git add bot/dynamic_stop_manager.py test_dynamic_stop_manager.py
git commit -m "Add dynamic stop manager - trend-based stop expansion"
```

---

## Final Deployment Steps

### 1. Push All Changes

```bash
git push origin deploy/trading-enhancements
```

### 2. Create Pull Request

Create PR with title: "Trading Enhancements: Entry Quality, Vol Sizing, Dynamic Stops, Safety Guards"

### 3. Deployment Checklist

Before merging:

- [ ] All tests pass
- [ ] Profitability assertion works (test both valid and invalid configs)
- [ ] Stop-loss validator passes
- [ ] All feature flags default to OFF
- [ ] Safety features locked ON
- [ ] Documentation reviewed

### 4. Deploy to Production

```bash
# Merge to main
git checkout main
git merge deploy/trading-enhancements
git push origin main

# Deploy
./deploy.sh

# Verify all feature flags are OFF
python -c "from bot.feature_flags import get_feature_flags; \
           print(get_feature_flags().get_all_flags())"

# Run profitability assertion test
python -c "from bot.profitability_assertion import assert_strategy_is_profitable; \
           assert_strategy_is_profitable([5.0, 3.5, 2.5], 1.25, 2.5, 'coinbase'); \
           print('✅ Profitability assertion working')"
```

### 5. Begin Phase 1 Rollout

See `FEATURE_FLAG_ROLLOUT_PLAN.md` for complete rollout strategy.

---

## Emergency Rollback

If anything goes wrong:

```bash
# Disable all new features immediately
export FEATURE_ENTRY_QUALITY_AUDIT=false
export FEATURE_VOLATILITY_ADAPTIVE_SIZING=false
export FEATURE_DYNAMIC_STOP_EXPANSION=false

# Restart
./restart_nija.sh

# Verify rollback
python -c "from bot.feature_flags import get_feature_flags; \
           print(get_feature_flags().get_all_flags())"
```

---

## Module Deployment Summary

| Module | Risk Level | Deploy Order | Validation Required |
|--------|-----------|--------------|---------------------|
| Profitability Assertion | LOW | 1 | Unit tests |
| Stop-Loss Validator | LOW | 2 | Scan test |
| Profitability Audit | LOW | 3 | Run report |
| Feature Flags | LOW | 4 | Flag test |
| Entry Quality | LOW | 5 | Unit tests + integration |
| Vol Sizing | MEDIUM | 6 | Unit tests + backtest |
| Dynamic Stops | MEDIUM-HIGH | 7 | Unit tests + manual review |

---

**Total Deployment Time:** ~2-4 hours (manual validation included)  
**Risk Level:** LOW (all features flag-controlled)  
**Rollback Time:** <1 minute (environment variables)
