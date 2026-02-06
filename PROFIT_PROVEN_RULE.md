# NIJA Profit Proven Rule Documentation

## Overview

The **Profit Proven Rule** system establishes objective, measurable criteria for validating that a trading strategy has demonstrated consistent profitability before being deployed with significant capital.

This system provides:
1. **Clear Success Criteria** - Unambiguous metrics for "proven profitable"
2. **Real-Time Tracking** - Continuous monitoring against criteria
3. **Audit Trail** - Complete record of all performance milestones
4. **Risk Protection** - Prevents premature scaling of unproven strategies

## Profit Proven Criteria

### Default Criteria

A strategy is considered "Profit Proven" when ALL of the following criteria are met:

| Criterion | Requirement | Purpose |
|-----------|-------------|---------|
| **Time Window** | ≥ 24 hours | Ensures strategy works across multiple market sessions |
| **Trade Count** | ≥ 50 trades | Ensures statistical significance |
| **Net Profit** | ≥ +5.0% | Ensures genuine profitability after all fees |
| **Max Drawdown** | ≤ 15.0% | Ensures acceptable risk management |
| **Win Rate** | ≥ 45.0% | Ensures reasonable trade quality |

### Why These Numbers?

- **24 hours**: Covers multiple market cycles, prevents lucky streaks from single sessions
- **50 trades**: Provides statistical significance (minimum sample size for confidence)
- **+5% net**: Accounts for real-world slippage, fees, and market impact
- **15% max DD**: Acceptable drawdown that won't trigger panic or margin calls
- **45% win rate**: Reasonable baseline (can be profitable with good R:R even at 40-50%)

### Customization

Criteria can be customized based on strategy type:

```python
from bot.profit_proven_rule import ProfitProvenCriteria, get_profit_proven_tracker

# Conservative criteria (for live trading with large capital)
conservative = ProfitProvenCriteria(
    min_time_hours=72.0,      # 3 days
    min_trades=100,            # 100 trades
    min_net_profit_pct=10.0,  # 10% profit
    max_drawdown_pct=10.0,    # Max 10% DD
    min_win_rate_pct=50.0     # 50% win rate
)

# Aggressive criteria (for experimental strategies)
aggressive = ProfitProvenCriteria(
    min_time_hours=12.0,       # 12 hours
    min_trades=25,             # 25 trades
    min_net_profit_pct=3.0,   # 3% profit
    max_drawdown_pct=20.0,    # Max 20% DD
    min_win_rate_pct=40.0     # 40% win rate
)

# Initialize tracker with custom criteria
tracker = get_profit_proven_tracker(criteria=conservative)
```

## Usage Guide

### 1. Initialize Tracker

```python
from bot.profit_proven_rule import (
    get_profit_proven_tracker,
    TradeRecord,
    ProfitProvenStatus
)
from datetime import datetime

# Get global tracker instance
tracker = get_profit_proven_tracker()

# Set initial capital
tracker.set_initial_capital(capital=1000.0)
```

### 2. Record Trades

```python
# After each completed trade
trade = TradeRecord(
    trade_id="TRD-001",
    timestamp=datetime.now(),
    symbol="BTC-USD",
    side="long",
    entry_price=50000.0,
    exit_price=51000.0,
    position_size_usd=100.0,
    gross_pnl_usd=2.0,
    fees_usd=0.20,
    net_pnl_usd=1.80,
    is_win=True
)

tracker.record_trade(trade)
```

### 3. Check Status

```python
# Check if strategy is profit proven
is_proven, status, metrics = tracker.check_profit_proven()

if is_proven:
    print("✅ Strategy is PROFIT PROVEN!")
    print(f"Net profit: {metrics['net_profit_pct']:.2f}%")
    print(f"Win rate: {metrics['win_rate_pct']:.1f}%")
    print(f"Trades: {metrics['trade_count']}")
else:
    print(f"Status: {status.value}")
    print(f"Progress: {metrics['trade_count']}/{tracker.criteria.min_trades} trades")
```

### 4. Generate Report

```python
# Get human-readable progress report
report = tracker.get_progress_report()
print(report)

# Output:
# ================================================================================
# PROFIT PROVEN STATUS REPORT
# ================================================================================
# Status: IN_PROGRESS
# 
# Criteria vs. Current Performance:
#   Time:       18.5h / 24.0h ⏳
#   Trades:     42 / 50 ⏳
#   Net Profit: 6.30% / 5.0% ✅
#   Drawdown:   8.20% / 15.0% max ✅
#   Win Rate:   52.4% / 45.0% ✅
# ...
```

### 5. Export for Audit

```python
# Export complete state to JSON
audit_data = tracker.export_to_json()

# Save to file
with open('profit_proven_audit.json', 'w') as f:
    f.write(audit_data)
```

## Integration with Trading System

### Pre-Trade Check

```python
def should_allow_trade(user_id: str, capital_tier: str) -> bool:
    """
    Check if trading should be allowed based on profit proven status.
    """
    tracker = get_profit_proven_tracker()
    is_proven, status, metrics = tracker.check_profit_proven()
    
    # For small accounts, allow trading without proof
    if capital_tier in ['micro', 'saver']:
        return True
    
    # For larger accounts, require proof
    if capital_tier in ['investor', 'baller']:
        if not is_proven:
            logger.warning(f"❌ Trading blocked for {user_id}: Strategy not profit proven")
            logger.warning(f"   Status: {status.value}")
            logger.warning(f"   Progress: {metrics['trade_count']}/{tracker.criteria.min_trades} trades")
            return False
    
    return True
```

### Post-Trade Recording

```python
def record_completed_trade(trade_data: Dict) -> None:
    """
    Record trade in profit proven tracker.
    """
    tracker = get_profit_proven_tracker()
    
    # Create trade record
    trade = TradeRecord(
        trade_id=trade_data['id'],
        timestamp=datetime.fromisoformat(trade_data['exit_time']),
        symbol=trade_data['symbol'],
        side=trade_data['side'],
        entry_price=trade_data['entry_price'],
        exit_price=trade_data['exit_price'],
        position_size_usd=trade_data['position_size'],
        gross_pnl_usd=trade_data['gross_pnl'],
        fees_usd=trade_data['fees'],
        net_pnl_usd=trade_data['net_pnl'],
        is_win=trade_data['net_pnl'] > 0
    )
    
    # Record trade
    tracker.record_trade(trade)
    
    # Check status after each trade
    is_proven, status, metrics = tracker.check_profit_proven()
    
    if status == ProfitProvenStatus.PROVEN and not tracker.status == ProfitProvenStatus.PROVEN:
        logger.info("=" * 80)
        logger.info("🎉 MILESTONE: Strategy is now PROFIT PROVEN!")
        logger.info("=" * 80)
        logger.info(tracker.get_progress_report())
```

## Status Meanings

| Status | Description | Action |
|--------|-------------|--------|
| `NOT_STARTED` | No trades recorded yet | Begin trading |
| `IN_PROGRESS` | Accumulating data, criteria not yet met | Continue trading |
| `PROVEN` | All criteria met ✅ | Strategy validated, can scale |
| `FAILED` | Time window passed but criteria not met ❌ | Review strategy, adjust approach |

## Best Practices

### 1. Start Small

Begin with minimal capital while building proof:

```python
# Phase 1: Build proof with small capital
if tracker.status == ProfitProvenStatus.IN_PROGRESS:
    max_position_size = 50.0  # $50 max
else:
    max_position_size = account_balance * 0.10  # 10% of account
```

### 2. Regular Reporting

Generate reports at regular intervals:

```python
import schedule

def log_progress():
    tracker = get_profit_proven_tracker()
    report = tracker.get_progress_report()
    logger.info(report)

# Log progress every 6 hours
schedule.every(6).hours.do(log_progress)
```

### 3. Milestone Notifications

Alert when milestones are reached:

```python
def check_milestones():
    is_proven, status, metrics = tracker.check_profit_proven()
    
    # Check individual criteria
    checks = metrics['checks']
    
    if checks['time_requirement'] and not hasattr(tracker, '_time_milestone_logged'):
        logger.info("✅ MILESTONE: Time requirement met!")
        tracker._time_milestone_logged = True
    
    if checks['trade_count_requirement'] and not hasattr(tracker, '_trades_milestone_logged'):
        logger.info("✅ MILESTONE: Trade count requirement met!")
        tracker._trades_milestone_logged = True
    
    # ... check other criteria
```

### 4. Reset After Major Changes

Reset tracker when strategy logic changes:

```python
def on_strategy_update():
    """Called when trading strategy is modified"""
    from bot.profit_proven_rule import ProfitProvenTracker
    
    # Create fresh tracker
    global _global_tracker
    _global_tracker = ProfitProvenTracker()
    
    logger.warning("⚠️ Strategy updated - Profit Proven status RESET")
    logger.warning("   Strategy must re-prove profitability")
```

## Audit Trail

Every trade recorded in the Profit Proven Tracker is also logged to the audit system:

```python
from bot.trading_audit_logger import get_audit_logger

# Audit logger automatically records:
# - Trade entries
# - Trade exits  
# - Profit proven checks
# - Status changes

# Query profit proven events
audit_logger = get_audit_logger()
events = audit_logger.query_events(
    event_type=AuditEventType.PROFIT_PROVEN_CHECK,
    user_id="platform",
    limit=50
)
```

## Performance Metrics

The tracker calculates comprehensive metrics:

```python
metrics = tracker.calculate_metrics()

# Available metrics:
# - trade_count: Total trades
# - win_count: Winning trades
# - loss_count: Losing trades
# - win_rate_pct: Win rate percentage
# - gross_profit_usd: Total gross P&L
# - total_fees_usd: Total fees paid
# - net_profit_usd: Net P&L after fees
# - net_profit_pct: Net profit as % of initial capital
# - drawdown_pct: Current drawdown from peak
# - time_elapsed_hours: Time since start
# - initial_capital: Starting capital
# - current_capital: Current capital
# - peak_capital: Highest capital reached
```

## FAQ

### Q: Can criteria be changed after trades are recorded?

**A:** Yes, but it's not recommended. Changing criteria mid-way invalidates the validation. If criteria must change, create a new tracker instance.

### Q: What if a strategy fails to meet criteria?

**A:** Status will change to `FAILED` after the time window passes. Review the metrics to understand why it failed, adjust the strategy, and start a new validation cycle.

### Q: Can multiple strategies be tracked separately?

**A:** Currently, the system uses a global tracker. For multiple strategies, create separate tracker instances:

```python
tracker_scalping = ProfitProvenTracker(criteria=aggressive_criteria)
tracker_swing = ProfitProvenTracker(criteria=conservative_criteria)
```

### Q: How is this different from backtesting?

**A:** Backtesting uses historical data. Profit Proven validation uses **live trading data** with real fills, real slippage, and real fees. This is forward-testing, not backtesting.

### Q: What happens if I restart the bot?

**A:** The tracker state is in memory. For persistence across restarts, export to JSON and reload:

```python
# Before shutdown
state = tracker.export_to_json()
with open('tracker_state.json', 'w') as f:
    f.write(state)

# After restart
import json
with open('tracker_state.json', 'r') as f:
    state_data = json.load(f)
    
# Manually reconstruct tracker from state
# (Auto-loading from saved state to be implemented)
```

## See Also

- [SECURITY.md](SECURITY.md) - Security controls and guardrails
- [AUDIT_LOGGING.md](AUDIT_LOGGING.md) - Audit logging system
- [HARD_CONTROLS.md](HARD_CONTROLS.md) - Position limits and risk controls
