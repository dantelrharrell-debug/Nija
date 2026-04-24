# RISK FREEZE Quick Reference Guide

**One-page guide for working with frozen risk configurations**

---

## 🔒 Core Principle

> **NO risk parameter changes go live without backtesting, simulation, versioning, and approval.**

This prevents the #1 cause of strategy degradation: ad-hoc parameter tweaks.

---

## ✅ ALLOWED: Reading Risk Parameters

```python
from bot.risk_config_versions import get_version_manager

# Get active risk configuration
version_manager = get_version_manager()
active_params = version_manager.get_active_parameters()

# Use approved parameters
max_position_size = active_params['max_position_size']
max_daily_loss = active_params['max_daily_loss']
stop_loss_multiplier = active_params['stop_loss_atr_multiplier']
```

---

## ❌ FORBIDDEN: Direct Parameter Changes

```python
# ❌ WRONG - This will trigger RISK FREEZE violation
MAX_POSITION_SIZE = 0.15  # Changed from 0.10

# ❌ WRONG - Direct modification
config['max_daily_loss'] = 0.03  # Changed from 0.025

# ❌ WRONG - Hardcoded values
def calculate_position_size():
    return balance * 0.12  # Should use active config!
```

**Pre-commit hook will block these changes!**

---

## ✅ APPROVED: Proposing Risk Changes

### Step 1: Create Proposal

```python
from bot.risk_config_versions import (
    get_version_manager,
    RiskParameterChange,
    BacktestResults,
    PaperTradingResults,
    Approval
)

version_manager = get_version_manager()

# Document what you want to change
changes = [
    RiskParameterChange(
        parameter='max_position_size',
        old_value=0.10,
        new_value=0.08,
        reason='Reduce exposure during high volatility period'
    ),
    RiskParameterChange(
        parameter='stop_loss_atr_multiplier',
        old_value=1.5,
        new_value=1.8,
        reason='Reduce premature stop-outs based on backtest analysis'
    )
]

# Create new version
new_params = active_params.copy()
new_params['max_position_size'] = 0.08
new_params['stop_loss_atr_multiplier'] = 1.8

version = version_manager.create_version(
    version='RISK_CONFIG_v1.1.0',
    author='Your Name',
    changes=changes,
    risk_parameters=new_params
)
```

### Step 2: Backtest (Required)

```bash
# Run backtests with new parameters
python bot/apex_backtest.py --config-version RISK_CONFIG_v1.1.0 --period 90days

# Must test minimum 3 months of historical data
```

```python
# Add backtest results
backtest_results = BacktestResults(
    period_start='2025-11-12',
    period_end='2026-02-12',
    win_rate=0.60,  # 60%
    max_drawdown=0.11,  # 11%
    sharpe_ratio=1.85,
    total_return=0.48,  # 48%
    total_trades=287,
    conclusion='Approved - win rate improved, drawdown reduced'
)

version_manager.add_backtest_results('RISK_CONFIG_v1.1.0', backtest_results)
```

### Step 3: Paper Trade (Required)

```bash
# Run paper trading with new parameters for minimum 2 weeks
python paper_trading_manager.py --config-version RISK_CONFIG_v1.1.0 --duration 14days
```

```python
# Add paper trading results
paper_results = PaperTradingResults(
    period_start='2026-01-29',
    period_end='2026-02-12',
    trades=47,
    win_rate=0.62,
    max_drawdown=0.09,
    conclusion='Approved - consistent with backtest'
)

version_manager.add_paper_trading_results('RISK_CONFIG_v1.1.0', paper_results)
```

### Step 4: Get Approvals (Required)

```python
# Technical Lead approval
version_manager.add_approval(
    'RISK_CONFIG_v1.1.0',
    Approval(
        role='Technical Lead',
        name='Alice Smith',
        date='2026-02-12T14:30:00Z',
        signature='APPROVED_ALICE_SMITH'
    )
)

# Risk Manager approval
version_manager.add_approval(
    'RISK_CONFIG_v1.1.0',
    Approval(
        role='Risk Manager',
        name='Bob Johnson',
        date='2026-02-12T15:00:00Z',
        signature='APPROVED_BOB_JOHNSON'
    )
)

# Strategy Developer approval
version_manager.add_approval(
    'RISK_CONFIG_v1.1.0',
    Approval(
        role='Strategy Developer',
        name='Carol Davis',
        date='2026-02-12T15:30:00Z',
        signature='APPROVED_CAROL_DAVIS'
    )
)
```

### Step 5: Activate Version

```python
# All requirements met - activate!
version_manager.activate_version('RISK_CONFIG_v1.1.0')

print("✅ RISK_CONFIG_v1.1.0 is now active")
```

---

## 🚨 Emergency Override (RARE)

**Use ONLY for critical situations:**
- Exchange changes margin requirements
- Regulatory compliance issue
- Active trading causing immediate capital loss

```python
from bot.risk_freeze_guard import get_risk_freeze_guard

guard = get_risk_freeze_guard()

# Declare emergency
guard.declare_emergency_override(
    reason="Coinbase increased margin requirements to 3x",
    authorized_by="Technical Lead - Emergency",
    parameters_changed=['max_leverage']
)

# Make minimal change
# Must get post-emergency approval within 48 hours!
```

---

## 📊 Check Current Status

### View Active Version

```python
version_manager = get_version_manager()
active = version_manager.get_active_version()

print(f"Active Version: {active.version}")
print(f"Status: {active.status}")
print(f"Approved: {active.is_approved()}")
```

### Generate Version Report

```python
report = version_manager.generate_version_report('RISK_CONFIG_v1.1.0')
print(report)
```

Output:
```
Risk Configuration Version Report
============================================================
Version: RISK_CONFIG_v1.1.0
Date: 2026-02-12T10:30:00
Author: Your Name
Status: approved

Changes:
------------------------------------------------------------
  • max_position_size
    Old: 0.1
    New: 0.08
    Reason: Reduce exposure during high volatility period

Backtest Results:
------------------------------------------------------------
  Period: 2025-11-12 to 2026-02-12
  Win Rate: 60.00%
  Max Drawdown: 11.00%
  Sharpe Ratio: 1.85
  ...

Approvals:
------------------------------------------------------------
  ✅ Technical Lead: Alice Smith (2026-02-12T14:30:00Z)
  ✅ Risk Manager: Bob Johnson (2026-02-12T15:00:00Z)
  ✅ Strategy Developer: Carol Davis (2026-02-12T15:30:00Z)

Can Activate: ✅ Yes
```

### List All Versions

```python
versions = version_manager.list_versions()
for v in versions:
    print(f"{v.version} - {v.status} - {v.date}")
```

---

## 🛡️ Pre-Commit Protection

Git pre-commit hook automatically checks for risk parameter changes:

```bash
# Hook runs automatically on commit
git commit -m "Update risk config"

# Output if violation detected:
🚨 RISK FREEZE VIOLATION DETECTED
================================================================================
📄 bot/apex_config.py
   • POSITION_SIZING['max_position_size'] = 0.15

⚠️  All risk parameter changes require:
   1. ✅ Backtesting (minimum 3 months)
   2. ✅ Paper Trading (minimum 2 weeks)
   3. ✅ Version documentation
   4. ✅ Multi-stakeholder approval

❌ No risk configuration version increment detected
================================================================================
```

To proceed, create version first:
```bash
# Create and approve version
python -c "from bot.risk_config_versions import ...; # create version

# Stage the version file
git add config/risk_versions/RISK_CONFIG_v1.1.0.json

# Commit again
git commit -m "Update risk config to v1.1.0 (approved)"
```

---

## 🔍 Troubleshooting

### "No active risk configuration version found"

```python
# Initialize with baseline
from bot.risk_freeze_guard import get_risk_freeze_guard
import json

guard = get_risk_freeze_guard()

# Load baseline from file
with open('config/risk_versions/baseline_risk_config.json') as f:
    baseline = json.load(f)

guard.set_baseline(baseline['risk_parameters'])
```

### "Cannot activate version - missing approvals"

```python
version = version_manager.get_version('RISK_CONFIG_v1.1.0')

# Check what's missing
if not version.is_approved():
    print("Missing approvals")
if not version.backtesting:
    print("Missing backtest results")
if not version.paper_trading:
    print("Missing paper trading results")
```

### Pre-commit hook blocking legitimate change

```bash
# For emergency only - bypasses hook
git commit --no-verify -m "Emergency fix"

# Must follow up with proper approval within 48 hours!
```

---

## 📚 Full Documentation

- **[RISK_FREEZE_POLICY.md](RISK_FREEZE_POLICY.md)** - Complete policy
- **[RISK_MANAGEMENT_GUIDE.md](RISK_MANAGEMENT_GUIDE.md)** - Risk system guide
- **bot/risk_freeze_guard.py** - Guard implementation
- **bot/risk_config_versions.py** - Versioning system

---

## 💡 Philosophy

> **"Discipline is choosing between what you want now and what you want most."**

Ad-hoc risk parameter tweaks are the #1 cause of strategy degradation. The RISK FREEZE enforces:
- **Patience** - Test before deploying
- **Discipline** - Follow the process
- **Rigor** - Document everything
- **Professionalism** - Operate like an institution

This is how real trading systems stay profitable long-term.

---

**Questions?** See full policy at [RISK_FREEZE_POLICY.md](RISK_FREEZE_POLICY.md)
