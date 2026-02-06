# NIJA Scaling Greenlight System

## Overview

The **Scaling Greenlight System** provides the exact criteria and reporting format required for users to unlock position scaling. Users start with small positions and must demonstrate profitability before being approved to trade with larger position sizes.

This system protects both users and the platform by ensuring only proven strategies are scaled.

## Greenlight Philosophy

### Start Small, Scale Smart

1. **Everyone starts at Tier 1 (Micro)**: $10-50 per trade
2. **Prove profitability**: Meet objective criteria with real trading
3. **Unlock scaling**: Get greenlight to scale to Tier 2 ($50-100)
4. **Continue proving**: Sustain performance to unlock higher tiers

### Why This Matters

- ❌ **Without Greenlight**: New users risk large losses testing unproven strategies
- ✅ **With Greenlight**: Users prove profitability at small scale before risking more capital
- 🎯 **Result**: Higher success rate, lower risk, confidence in scaling decisions

## Scaling Tiers

| Tier | Name | Position Size | Requirement |
|------|------|---------------|-------------|
| 0 | LOCKED | $0 | Blocked (violations) |
| 1 | MICRO | $10 - $50 | Default starting tier |
| 2 | SMALL | $50 - $100 | Greenlight approval required |
| 3 | MEDIUM | $100 - $500 | Sustained Tier 2 performance |
| 4 | LARGE | $500 - $1,000 | Sustained Tier 3 performance |

## Greenlight Criteria

### Minimum Requirements (ALL must be met)

| Criterion | Requirement | Why |
|-----------|-------------|-----|
| **Net Profit** | ≥ $50 | Absolute minimum profit to validate strategy |
| **ROI** | ≥ 5% | Percentage return validates scalability |
| **Win Rate** | ≥ 45% | Trade quality indicator |
| **Max Drawdown** | ≤ 15% | Risk management validation |
| **Trade Count** | ≥ 50 trades | Statistical significance |
| **Time Period** | ≥ 24 hours | Multiple market sessions |
| **Kill Switch Triggers** | 0 | No trading halts |
| **Daily Limit Hits** | 0 | No limit violations |
| **Position Rejections** | ≤ 5% | Proper position sizing |

### Example Scenarios

#### ✅ APPROVED

```
Net Profit:    $75.50 ✅
ROI:           7.55% ✅
Win Rate:      52% ✅
Drawdown:      8.2% ✅
Trades:        63 ✅
Time:          28 hours ✅
Violations:    0 ✅

RESULT: GREENLIGHT APPROVED → Tier 2 (SMALL)
```

#### ❌ NOT APPROVED (Insufficient Profit)

```
Net Profit:    $32.00 ❌ (need $50)
ROI:           6.4% ✅
Win Rate:      48% ✅
Drawdown:      9.5% ✅
Trades:        55 ✅
Time:          26 hours ✅
Violations:    0 ✅

RESULT: Continue testing at Tier 1
```

#### ❌ NOT APPROVED (Risk Violation)

```
Net Profit:    $95.00 ✅
ROI:           9.5% ✅
Win Rate:      54% ✅
Drawdown:      18.5% ❌ (max 15%)
Trades:        72 ✅
Time:          36 hours ✅
Violations:    0 ✅

RESULT: Continue testing - improve risk management
```

## The Greenlight Report

### What It Contains

The greenlight report is the EXACT document that determines scaling approval. It includes:

1. **Overall Status**: BLOCKED, TESTING, GREENLIT, or SCALED
2. **Tier Information**: Current tier and approved tier
3. **Performance Metrics**: All profit and risk metrics
4. **Criteria Checks**: Pass/fail for each requirement
5. **Decision**: Approved or not approved
6. **Next Steps**: Specific actions to take

### Report Format

#### Text Report

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
     - Kill Switch Triggers: 0
     - Daily Limit Hits: 0
     - Position Rejections: 2 (3.2%)

================================================================================
DECISION
================================================================================

🎉 GREENLIGHT APPROVED 🎉

Congratulations! You have met all criteria for scaling.
You are approved to scale to Tier 2 (SMALL).

Position Limits:
  New: $50 - $100 per trade

================================================================================
NEXT STEPS
================================================================================
1. ✅ You are approved to scale to Tier 2 (SMALL)
2. Contact support or update your account settings to activate new tier
3. Continue trading consistently to maintain tier status
================================================================================
```

#### JSON Report

```json
{
  "report_id": "GLR-20260206145823-0001",
  "timestamp": "2026-02-06T14:58:23.123456Z",
  "user_id": "john_smith",
  "greenlight_status": "greenlit",
  "current_tier": 1,
  "approved_tier": 2,
  "net_profit_usd": 75.50,
  "roi_pct": 7.55,
  "win_rate_pct": 52.4,
  "drawdown_pct": 8.20,
  "trade_count": 63,
  "time_elapsed_hours": 28.5,
  "kill_switch_triggers": 0,
  "daily_limit_hits": 0,
  "position_rejections": 2,
  "position_rejection_pct": 3.2,
  "profit_check": true,
  "roi_check": true,
  "win_rate_check": true,
  "drawdown_check": true,
  "trade_count_check": true,
  "time_check": true,
  "risk_violations_check": true,
  "all_criteria_met": true,
  "next_steps": [
    "✅ You are approved to scale to Tier 2 (SMALL)",
    "Contact support or update your account settings to activate new tier",
    "Continue trading consistently to maintain tier status"
  ],
  "criteria_used": {
    "min_net_profit_usd": 50.0,
    "min_roi_pct": 5.0,
    "max_drawdown_pct": 15.0,
    "min_win_rate_pct": 45.0,
    "min_trades": 50,
    "min_time_hours": 24.0,
    "max_kill_switch_triggers": 0,
    "max_daily_limit_hits": 0,
    "max_position_rejections_pct": 5.0
  }
}
```

## How to Generate a Greenlight Report

### Method 1: Using the CLI Tool

```bash
# Generate report for default user
python generate_greenlight_report.py

# Generate report for specific user
python generate_greenlight_report.py --user john_smith

# Save to file
python generate_greenlight_report.py --user john_smith --output greenlight_report.txt

# Output as JSON
python generate_greenlight_report.py --user john_smith --json > report.json

# Specify current tier
python generate_greenlight_report.py --user john_smith --tier small
```

### Method 2: Programmatic Generation

```python
from bot.scaling_greenlight import get_greenlight_system, ScalingTier
from bot.profit_proven_rule import get_profit_proven_tracker
from controls import get_hard_controls

# Get performance metrics
tracker = get_profit_proven_tracker()
is_proven, status, performance_metrics = tracker.check_profit_proven()

# Get risk metrics
hard_controls = get_hard_controls()
risk_stats = hard_controls.get_rejection_stats(user_id="john_smith")

risk_metrics = {
    'kill_switch_triggers': 0,
    'daily_limit_hits': 0,
    'position_rejections': risk_stats['rejected'],
    'total_validations': risk_stats['total_validations'],
}

# Generate report
greenlight_system = get_greenlight_system()
report = greenlight_system.generate_greenlight_report(
    user_id="john_smith",
    current_tier=ScalingTier.MICRO,
    performance_metrics=performance_metrics,
    risk_metrics=risk_metrics
)

# Display text report
print(report.to_text_report())

# Or export as JSON
import json
print(json.dumps(report.to_dict(), indent=2))
```

## Integration with Trading System

### Pre-Trade Check

```python
def can_use_position_size(user_id: str, position_size_usd: float) -> bool:
    """Check if user can use requested position size based on tier"""
    from bot.scaling_greenlight import get_greenlight_system, ScalingTier
    from bot.user_tier_tracker import get_user_tier  # Hypothetical
    
    greenlight = get_greenlight_system()
    user_tier = get_user_tier(user_id)
    
    # Get tier limits
    limits = greenlight.get_tier_limits(user_tier)
    
    if position_size_usd < limits['min']:
        logger.warning(f"Position too small for tier: ${position_size_usd} < ${limits['min']}")
        return False
    
    if position_size_usd > limits['max']:
        logger.warning(f"Position too large for tier: ${position_size_usd} > ${limits['max']}")
        return False
    
    return True
```

### Automatic Tier Progression

```python
def check_tier_progression(user_id: str):
    """Check if user is ready for tier progression"""
    from bot.scaling_greenlight import get_greenlight_system, ScalingTier
    from bot.profit_proven_rule import get_profit_proven_tracker
    from controls import get_hard_controls
    
    # Get current tier
    current_tier = get_user_tier(user_id)
    
    # Don't check if already at max tier
    if current_tier == ScalingTier.LARGE:
        return
    
    # Get metrics
    tracker = get_profit_proven_tracker()
    _, _, perf_metrics = tracker.check_profit_proven()
    
    controls = get_hard_controls()
    risk_stats = controls.get_rejection_stats(user_id)
    risk_metrics = {
        'kill_switch_triggers': 0,
        'daily_limit_hits': 0,
        'position_rejections': risk_stats['rejected'],
        'total_validations': risk_stats['total_validations'],
    }
    
    # Generate report
    greenlight = get_greenlight_system()
    report = greenlight.generate_greenlight_report(
        user_id=user_id,
        current_tier=current_tier,
        performance_metrics=perf_metrics,
        risk_metrics=risk_metrics
    )
    
    # Check if approved for higher tier
    if report.all_criteria_met and report.approved_tier.value > current_tier.value:
        logger.info(f"🎉 User {user_id} approved for tier {report.approved_tier.name}!")
        logger.info(report.to_text_report())
        
        # Send notification
        send_tier_progression_notification(user_id, report)
        
        # Auto-upgrade (or require manual confirmation)
        # upgrade_user_tier(user_id, report.approved_tier)
```

### Scheduled Greenlight Checks

```python
import schedule

def scheduled_greenlight_check():
    """Run greenlight checks for all active users"""
    from bot.scaling_greenlight import get_greenlight_system, ScalingTier
    
    active_users = get_active_users()
    
    for user in active_users:
        # Skip users at max tier
        if user.tier == ScalingTier.LARGE:
            continue
        
        # Generate report
        report = generate_user_greenlight_report(user.id, user.tier)
        
        # Log if ready for progression
        if report.all_criteria_met:
            logger.info(f"User {user.id} ready for tier progression!")
            notify_user_greenlight_approved(user.id, report)

# Run daily at midnight
schedule.every().day.at("00:00").do(scheduled_greenlight_check)
```

## Best Practices

### 1. Regular Reporting

Generate greenlight reports at regular intervals:

- After every 10 trades
- After every 8 hours of trading
- Daily at EOD
- On user request

### 2. Transparent Communication

Share greenlight reports with users:

```python
def share_progress_with_user(user_id: str):
    """Send progress report to user"""
    report = generate_greenlight_report(user_id)
    
    email_body = f"""
    Hi {user_id},
    
    Here's your progress toward scaling approval:
    
    {report.to_text_report()}
    
    Questions? Contact support.
    
    Happy trading!
    NIJA Team
    """
    
    send_email(user_id, "Your Scaling Progress Report", email_body)
```

### 3. Archive Reports

Keep historical greenlight reports:

```python
def save_greenlight_report(report):
    """Save report for historical tracking"""
    import os
    from pathlib import Path
    
    # Create reports directory
    reports_dir = Path("./data/greenlight_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as JSON
    filename = f"{report.user_id}_{report.report_id}.json"
    filepath = reports_dir / filename
    
    with open(filepath, 'w') as f:
        f.write(report.to_json())
    
    logger.info(f"Greenlight report saved: {filepath}")
```

### 4. Audit Trail Integration

Log greenlight decisions to audit system:

```python
from bot.trading_audit_logger import get_audit_logger, AuditEventType

def log_greenlight_decision(report):
    """Log greenlight report to audit trail"""
    audit_logger = get_audit_logger()
    
    audit_logger.log_event(
        event_type=AuditEventType.PROFIT_PROVEN_CHECK,
        user_id=report.user_id,
        event_data={
            'report_id': report.report_id,
            'greenlight_status': report.greenlight_status,
            'current_tier': report.current_tier,
            'approved_tier': report.approved_tier,
            'all_criteria_met': report.all_criteria_met,
            'performance': {
                'net_profit_usd': report.net_profit_usd,
                'roi_pct': report.roi_pct,
                'win_rate_pct': report.win_rate_pct,
                'trade_count': report.trade_count,
            }
        },
        validation_result=report.all_criteria_met
    )
```

## FAQ

### Q: Can criteria be customized per user?

**A:** Yes. Create custom criteria for specific user types:

```python
from bot.scaling_greenlight import GreenlightCriteria, ScalingGreenlightSystem

# Conservative criteria for risk-averse users
conservative = GreenlightCriteria(
    min_net_profit_usd=100.0,
    min_roi_pct=10.0,
    min_win_rate_pct=50.0,
    max_drawdown_pct=10.0,
    min_trades=100,
    min_time_hours=48.0
)

# Use custom criteria
greenlight = ScalingGreenlightSystem(criteria=conservative)
```

### Q: What if a user's performance degrades after getting greenlight?

**A:** Implement tier demotion:

- Monitor performance continuously
- If drawdown exceeds threshold, demote to lower tier
- Require re-validation before scaling back up

### Q: Can users skip tiers?

**A:** No. Users must progress tier by tier:
- Tier 1 → Tier 2 → Tier 3 → Tier 4

This ensures sustained performance at each level.

### Q: What happens if criteria aren't met after 24 hours?

**A:** User continues at current tier. There's no penalty for not meeting criteria - users can continue testing indefinitely.

### Q: Are there different criteria for different trading styles?

**A:** Yes, criteria can be customized:

```python
# Day trading (more trades, shorter time)
day_trading = GreenlightCriteria(
    min_trades=100,
    min_time_hours=12.0,
    min_win_rate_pct=48.0
)

# Swing trading (fewer trades, longer time)
swing_trading = GreenlightCriteria(
    min_trades=25,
    min_time_hours=72.0,
    min_win_rate_pct=55.0
)
```

## See Also

- [PROFIT_PROVEN_RULE.md](PROFIT_PROVEN_RULE.md) - Profit proven validation system
- [AUDIT_LOGGING.md](AUDIT_LOGGING.md) - Audit logging system
- [HARD_CONTROLS.md](HARD_CONTROLS.md) - Position limits and risk controls
- [SECURITY.md](SECURITY.md) - Overall security architecture
