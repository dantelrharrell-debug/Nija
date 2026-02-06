# NIJA Hard Controls Summary

## Overview

This document provides a complete summary of the hard controls, profit proven rules, audit logging, and scaling greenlight systems implemented in NIJA.

## 1. Profit Proven Rule

### Definition

A strategy is "Profit Proven" when ALL of the following criteria are met:

```
✅ Time Window:     ≥ 24 hours (multiple market sessions)
✅ Trade Count:     ≥ 50 trades (statistical significance)
✅ Net Profit:      ≥ +5% (after all fees)
✅ Max Drawdown:    ≤ 15% (risk management validated)
✅ Win Rate:        ≥ 45% (trade quality validated)
```

### Why These Numbers?

- **24 hours**: Covers multiple market cycles, prevents single-session luck
- **50 trades**: Minimum sample size for statistical confidence
- **+5% NET**: Real-world profitability after slippage and fees
- **15% drawdown**: Acceptable risk that won't trigger panic
- **45% win rate**: Realistic baseline (profitable with good R:R)

### Usage

```python
from bot.profit_proven_rule import get_profit_proven_tracker, TradeRecord

tracker = get_profit_proven_tracker()
tracker.set_initial_capital(1000.0)

# Record trades
tracker.record_trade(trade_record)

# Check status
is_proven, status, metrics = tracker.check_profit_proven()
```

**Documentation**: [PROFIT_PROVEN_RULE.md](PROFIT_PROVEN_RULE.md)

## 2. Hard Max Position Rule

### Unbypasable Position Limits

Position sizing has **4 layers of protection**:

```
Layer 1: Minimum     →  2% of account
Layer 2: Maximum     → 10% of account
Layer 3: Absolute %  → 15% of account (UNBYPASABLE)
Layer 4: Absolute $  → $10,000 (UNBYPASABLE)
```

### What "Unbypasable" Means

- **No exceptions**: Cannot be overridden by any user or code
- **No workarounds**: All code paths check these limits
- **No configuration**: Hard-coded constants, not env variables
- **Audit trail**: Every validation logged with pass/fail

### Example Validations

```python
Account: $1,000

✅ PASS: $50  (5%)   - Normal position
✅ PASS: $100 (10%)  - Maximum allowed
❌ FAIL: $150 (15%)  - Exceeds 10% limit
❌ FAIL: $200 (20%)  - 🚨 Exceeds 15% ABSOLUTE CAP

Account: $100,000

✅ PASS: $5,000  (5%)   - Normal position
✅ PASS: $10,000 (10%)  - Maximum allowed
❌ FAIL: $11,000 (11%)  - 🚨 Exceeds $10k ABSOLUTE CAP
```

### Usage

```python
from controls import get_hard_controls

controls = get_hard_controls()

is_valid, error = controls.validate_position_size(
    user_id="platform",
    position_size_usd=100.0,
    account_balance=1000.0,
    symbol="BTC-USD"
)

if not is_valid:
    print(f"Position rejected: {error}")
```

**Location**: `controls/__init__.py`

## 3. Audit-Proof Log Format

### Exact Format

Every audit event uses this standardized format:

```json
{
  "event_id": "AE-20260206145823123456-000042",
  "event_type": "trade_entry",
  "timestamp": "2026-02-06T14:58:23.123456Z",
  "user_id": "platform",
  "account_id": "coinbase_main",
  "broker": "coinbase",
  "trade_id": "TRD-BTC-20260206-001",
  "symbol": "BTC-USD",
  "event_data": {
    "side": "long",
    "entry_price": 50000.0,
    "stop_loss": 49500.0,
    "take_profit": 51000.0
  },
  "validation_result": true,
  "position_size_usd": 100.0,
  "account_balance_usd": 1000.0,
  "checksum": "a7f3c2d1e4b5a6c8f9d0e1a2b3c4d5e6..."
}
```

### Key Features

1. **Tamper-Evident**: SHA-256 checksum on every entry
2. **Structured**: Machine-readable JSON format
3. **Complete**: Full trade lifecycle (entry → exits → P&L)
4. **Queryable**: Filter by event type, user, trade, time
5. **Audit-Compliant**: Meets regulatory requirements

### Event Types

- `trade_entry` - Trade opened
- `trade_exit` - Trade closed
- `position_size_validation` - Position approved
- `position_size_rejected` - Position rejected
- `profit_proven_achieved` - Profit proven milestone
- `kill_switch_triggered` - Trading halted

### Usage

```python
from bot.trading_audit_logger import get_audit_logger

audit_logger = get_audit_logger()

# Log trade entry
audit_logger.log_trade_entry(
    user_id="platform",
    trade_id="TRD-001",
    symbol="BTC-USD",
    side="long",
    entry_price=50000.0,
    position_size_usd=100.0,
    stop_loss=49500.0,
    take_profit=51000.0,
    account_balance_usd=1000.0,
    broker="coinbase"
)

# Verify checksum
entry = audit_logger.query_events(trade_id="TRD-001")[0]
is_valid = entry.verify_checksum()  # Returns True/False
```

**Documentation**: [AUDIT_LOGGING.md](AUDIT_LOGGING.md)

## 4. Scaling Greenlight Report

### Exact Greenlight Criteria

To unlock scaling from Tier 1 (MICRO) to Tier 2 (SMALL), users must meet ALL criteria:

```
✅ Net Profit:       ≥ $50 (absolute minimum)
✅ ROI:              ≥ 5% (scalability indicator)
✅ Win Rate:         ≥ 45% (trade quality)
✅ Max Drawdown:     ≤ 15% (risk management)
✅ Trade Count:      ≥ 50 trades (statistical significance)
✅ Time Period:      ≥ 24 hours (multiple sessions)
✅ Kill Switches:    0 triggers (clean record)
✅ Daily Limits:     0 hits (no violations)
✅ Position Rejects: ≤ 5% (proper sizing)
```

### Scaling Tiers

| Tier | Name | Position Size | Unlock Requirement |
|------|------|---------------|-------------------|
| 0 | LOCKED | $0 | N/A (blocked) |
| 1 | MICRO | $10 - $50 | Default starting tier |
| 2 | SMALL | $50 - $100 | Greenlight approval |
| 3 | MEDIUM | $100 - $500 | Sustained Tier 2 performance |
| 4 | LARGE | $500 - $1,000 | Sustained Tier 3 performance |

### Exact Report Format

```
================================================================================
NIJA SCALING GREENLIGHT REPORT
================================================================================
Report ID:  GLR-20260206145823-0001
Date:       2026-02-06T14:58:23.123456Z
User:       john_smith

CURRENT STATUS: GREENLIT
Current Tier:   Tier 1 (MICRO)
Approved Tier:  Tier 2 (SMALL)

================================================================================
CRITERIA EVALUATION
================================================================================

Performance Requirements:
  ✅ Net Profit:     $75.50
  ✅ ROI:            7.55%
  ✅ Win Rate:       52.4%
  ✅ Drawdown:       8.20%

Statistical Requirements:
  ✅ Trade Count:    63 trades
  ✅ Time Period:    28.5 hours

Risk Management:
  ✅ No Violations:  Clean record

================================================================================
DECISION
================================================================================

🎉 GREENLIGHT APPROVED 🎉

You are approved to scale to Tier 2 (SMALL).
Position Limits: $50 - $100 per trade

================================================================================
NEXT STEPS
================================================================================
1. ✅ Contact support to activate Tier 2
2. Continue trading to maintain tier status
3. Build track record for Tier 3 progression
================================================================================
```

### Generating Reports

#### Command Line

```bash
# Generate greenlight report
python generate_greenlight_report.py --user john_smith

# Save to file
python generate_greenlight_report.py --user john_smith --output report.txt

# JSON output
python generate_greenlight_report.py --user john_smith --json > report.json
```

#### Programmatic

```python
from bot.scaling_greenlight import get_greenlight_system, ScalingTier

greenlight = get_greenlight_system()

report = greenlight.generate_greenlight_report(
    user_id="john_smith",
    current_tier=ScalingTier.MICRO,
    performance_metrics=metrics,
    risk_metrics=risk_data
)

# Text report
print(report.to_text_report())

# JSON report
print(report.to_json())
```

**Documentation**: [SCALING_GREENLIGHT.md](SCALING_GREENLIGHT.md)

## 5. Integration Example

### Complete Workflow

```python
from bot.profit_proven_rule import get_profit_proven_tracker, TradeRecord
from bot.trading_audit_logger import get_audit_logger
from bot.scaling_greenlight import get_greenlight_system, ScalingTier
from controls import get_hard_controls
from datetime import datetime

# Initialize systems
tracker = get_profit_proven_tracker()
tracker.set_initial_capital(1000.0)
audit_logger = get_audit_logger()
greenlight = get_greenlight_system()
controls = get_hard_controls()

# Before trade: Validate position size
is_valid, error = controls.validate_position_size(
    user_id="john_smith",
    position_size_usd=50.0,
    account_balance=1000.0,
    symbol="BTC-USD"
)

if not is_valid:
    print(f"❌ Position rejected: {error}")
    exit()

# Execute trade
# ... (trade execution code)

# After trade: Log to audit
audit_logger.log_trade_entry(
    user_id="john_smith",
    trade_id="TRD-001",
    symbol="BTC-USD",
    side="long",
    entry_price=50000.0,
    position_size_usd=50.0,
    stop_loss=49500.0,
    take_profit=51000.0,
    account_balance_usd=1000.0,
    broker="coinbase"
)

# When trade closes: Record to profit tracker
trade_record = TradeRecord(
    trade_id="TRD-001",
    timestamp=datetime.now(),
    symbol="BTC-USD",
    side="long",
    entry_price=50000.0,
    exit_price=51000.0,
    position_size_usd=50.0,
    gross_pnl_usd=20.0,
    fees_usd=0.40,
    net_pnl_usd=19.60,
    is_win=True
)

tracker.record_trade(trade_record)

# Log exit to audit
audit_logger.log_trade_exit(
    user_id="john_smith",
    trade_id="TRD-001",
    symbol="BTC-USD",
    exit_type="take_profit",
    exit_price=51000.0,
    exit_size_pct=1.0,
    gross_pnl_usd=20.0,
    fees_usd=0.40,
    net_pnl_usd=19.60,
    account_balance_usd=1019.60,
    exit_reason="Take profit hit"
)

# Periodically: Check greenlight status
is_proven, status, metrics = tracker.check_profit_proven()

if is_proven:
    # Generate greenlight report
    risk_stats = controls.get_rejection_stats(user_id="john_smith")
    risk_metrics = {
        'kill_switch_triggers': 0,
        'daily_limit_hits': 0,
        'position_rejections': risk_stats['rejected'],
        'total_validations': risk_stats['total_validations'],
    }
    
    report = greenlight.generate_greenlight_report(
        user_id="john_smith",
        current_tier=ScalingTier.MICRO,
        performance_metrics=metrics,
        risk_metrics=risk_metrics
    )
    
    if report.all_criteria_met:
        print("🎉 User ready for tier progression!")
        print(report.to_text_report())
```

## 6. Files Reference

### Core Implementation

| File | Purpose |
|------|---------|
| `bot/profit_proven_rule.py` | Profit proven tracking system |
| `bot/trading_audit_logger.py` | Audit logging with checksums |
| `bot/scaling_greenlight.py` | Tier progression system |
| `controls/__init__.py` | Hard controls with unbypasable limits |

### Tools

| File | Purpose |
|------|---------|
| `generate_greenlight_report.py` | CLI tool for greenlight reports |
| `test_profit_and_greenlight_systems.py` | Test suite |

### Documentation

| File | Purpose |
|------|---------|
| `PROFIT_PROVEN_RULE.md` | Profit proven system guide |
| `AUDIT_LOGGING.md` | Audit logging documentation |
| `SCALING_GREENLIGHT.md` | Scaling tier system guide |
| `HARD_CONTROLS.md` | This document |

## 7. Key Guarantees

### Guarantee 1: No Unbypasable Limits Can Be Exceeded

✅ **Absolute Max Position**: 15% or $10,000 (whichever is smaller)  
✅ **Enforced In**: Every position validation call  
✅ **Logged To**: Audit trail with rejection reason  
✅ **Cannot Be**: Overridden, configured, or bypassed  

### Guarantee 2: Complete Audit Trail

✅ **Every Trade**: Logged with entry and exit  
✅ **Every Position Validation**: Logged with approval/rejection  
✅ **Every Milestone**: Logged (profit proven, greenlight)  
✅ **Tamper-Evident**: SHA-256 checksum on every entry  

### Guarantee 3: Objective Scaling Criteria

✅ **Exact Criteria**: $50 profit, 5% ROI, 50 trades, 24h, 0 violations  
✅ **Exact Report**: Standardized format with pass/fail  
✅ **No Subjectivity**: Fully automated evaluation  
✅ **No Bypassing**: Must meet ALL criteria  

## 8. Testing

Run the comprehensive test suite:

```bash
python test_profit_and_greenlight_systems.py
```

Expected output:
```
✅ All tests passed successfully!

Final Status:
  Profit Proven: YES ✅
  Greenlight: GREENLIT
  Tier: 1 → 2
```

## See Also

- [PROFIT_PROVEN_RULE.md](PROFIT_PROVEN_RULE.md) - Detailed profit proven documentation
- [AUDIT_LOGGING.md](AUDIT_LOGGING.md) - Complete audit logging guide
- [SCALING_GREENLIGHT.md](SCALING_GREENLIGHT.md) - Tier progression documentation
- [SECURITY.md](SECURITY.md) - Overall security architecture
