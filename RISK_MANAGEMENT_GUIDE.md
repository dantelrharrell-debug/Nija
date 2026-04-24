# NIJA Risk Management System

## Overview

NIJA's risk management system implements **7 critical operational features** designed to make the bot:
- 🧱 **Structurally Safe** - Prevents systematic issues
- 🧮 **Capital-Efficient** - Optimizes capital usage
- 🔒 **Risk-Contained** - Limits downside exposure
- 📈 **Scalable** - Ready for larger balances
- 🧠 **Trustworthy** - Transparent and auditable

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   NIJA Risk Management                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │ Minimum Notional │  │  Fee-Aware       │               │
│  │ Guard            │  │  Position Sizing │               │
│  └──────────────────┘  └──────────────────┘               │
│           ▼                      ▼                          │
│  ┌─────────────────────────────────────────┐               │
│  │   Order Validation Pipeline             │               │
│  └─────────────────────────────────────────┘               │
│           ▼                                                 │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │ Capital          │  │  Kill Switch     │               │
│  │ Reservation      │  │  Auto-Triggers   │               │
│  └──────────────────┘  └──────────────────┘               │
│           ▼                      ▼                          │
│  ┌─────────────────────────────────────────┐               │
│  │   Trade Execution Engine                │               │
│  └─────────────────────────────────────────┘               │
│           ▼                                                 │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │ Reconciliation   │  │  Performance     │               │
│  │ Watchdog         │  │  Attribution     │               │
│  └──────────────────┘  └──────────────────┘               │
│           ▼                      ▼                          │
│  ┌─────────────────────────────────────────┐               │
│  │   Monitoring & Alerting System          │               │
│  └─────────────────────────────────────────┘               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Features

### 1️⃣ Minimum Notional Guard

**Purpose**: Prevent fragmentation by blocking positions below minimum value.

**Implementation**: `bot/minimum_notional_guard.py`

**Key Features**:
- Hard block on orders under $3-$5 USD (configurable by exchange)
- Kraken-friendly defaults ($10 minimum)
- Balance-adaptive minimums for different account sizes
- Integration with existing validators

**Usage**:
```python
from bot.minimum_notional_guard import get_notional_guard, should_block_order

# Check if order should be blocked
blocked = should_block_order(
    size=0.01,           # BTC amount
    price=50000.0,       # $50k per BTC
    exchange='kraken',
    balance=100.0,
    symbol='BTC-USD'
)

if blocked:
    print("Order blocked - below minimum notional")
```

**Configuration**:
```python
# Global minimum (all exchanges)
GLOBAL_MIN_NOTIONAL_USD = 5.0

# Exchange-specific minimums
ExchangeMinimums.COINBASE = 2.0
ExchangeMinimums.KRAKEN = 10.0
ExchangeMinimums.BINANCE = 10.0

# Balance-adaptive minimums
MIN_NOTIONAL_BY_BALANCE = {
    'micro': 3.0,      # < $50 balance
    'small': 5.0,      # $50-$500
    'medium': 10.0,    # $500-$5000
    'large': 15.0,     # > $5000
}
```

**Benefits**:
- ✅ Prevents unprofitable micro-positions
- ✅ Stops fragmentation before it happens
- ✅ Reduces exchange rejection rate
- ✅ Improves fee efficiency

---

### 2️⃣ Fee-Aware Position Sizing

**Purpose**: Abort trades where fees would consume excessive profit potential.

**Implementation**: Enhanced `bot/validators/fee_validator.py`

**Key Features**:
- Pre-trade fee estimation
- Abort if `expected_fee > 2%` of position size (configurable)
- Fee impact warnings
- Profitability validation

**Usage**:
```python
from bot.validators.fee_validator import FeeValidator

validator = FeeValidator()

# Validate fee-to-position ratio
result = validator.validate_fee_to_position_ratio(
    position_size=0.01,
    entry_price=50000.0,
    broker='coinbase',
    max_fee_pct=2.0,  # 2% max
    symbol='BTC-USD'
)

if result.level == ValidationLevel.ERROR:
    print(f"ABORT: {result.message}")
    # Don't place order
```

**Benefits**:
- ✅ Prevents fee-eroded trades
- ✅ Improves net P&L significantly
- ✅ Better than most indicators for profitability
- ✅ Automatic fee optimization

---

### 3️⃣ Capital Reservation Manager

**Purpose**: Prevent over-promising capital with small accounts.

**Implementation**: `bot/capital_reservation_manager.py`

**Key Features**:
- Reserve capital per open position
- Safety buffer enforcement (default 20%)
- Free capital tracking
- Thread-safe operations

**Usage**:
```python
from bot.capital_reservation_manager import (
    get_capital_reservation_manager,
    can_open_position
)

manager = get_capital_reservation_manager(
    safety_buffer_pct=0.20,  # 20% buffer
    min_free_capital_usd=5.0
)

# Check if new position can be opened
can_open, msg, details = manager.can_open_position(
    total_balance=100.0,
    new_position_size=30.0
)

if can_open:
    # Reserve capital
    manager.reserve_capital(
        position_id="pos1",
        amount=30.0,
        symbol="BTC-USD"
    )
else:
    print(f"Cannot open: {msg}")
```

**Configuration**:
```python
# Safety buffer (% of balance to keep free)
safety_buffer_pct = 0.20  # 20%

# Minimum free capital (USD)
min_free_capital_usd = 5.0
```

**Benefits**:
- ✅ Prevents overlapping partial fills
- ✅ Stops silent leverage via fragmentation
- ✅ Ensures capital for emergency exits
- ✅ Transparent capital allocation

---

### 4️⃣ Global Kill Switch (Enhanced)

**Purpose**: Atomic brake for various risk scenarios.

**Implementation**: Enhanced `bot/kill_switch.py`

**Key Features**:
- **Auto-Triggers**:
  - Max daily loss % (default 10%)
  - Consecutive losing trades (default 5)
  - API instability (10+ consecutive errors)
  - Unexpected balance delta (50%+ change)
- **Exit-Only Mode**: Positions still managed, but no new entries
- **Multi-Activation**: UI, CLI, ENV, File system, Auto
- **Audit Trail**: All activations logged with timestamp and reason

**Usage**:
```python
from bot.kill_switch import get_kill_switch, get_auto_trigger

# Manual activation
kill_switch = get_kill_switch()
kill_switch.activate("Manual stop - suspicious activity", "MANUAL")

# Auto-trigger setup
auto_trigger = get_auto_trigger(
    max_daily_loss_pct=10.0,
    max_consecutive_losses=5,
    enable_auto_trigger=True
)

# Check and auto-trigger if needed
current_balance = 90.0  # Started at 100
triggered = auto_trigger.auto_trigger_if_needed(
    current_balance=current_balance,
    last_trade_result=False  # Last trade was a loss
)

# Check before every trade
if kill_switch.is_active():
    print("Cannot trade - kill switch active")
    return
```

**Configuration**:
```python
# Auto-trigger thresholds
max_daily_loss_pct = 10.0        # 10% daily loss
max_consecutive_losses = 5        # 5 losses in a row
max_consecutive_api_errors = 10   # 10 API failures
max_balance_delta_pct = 50.0      # 50% unexpected change
```

**Benefits**:
- ✅ Professional-grade circuit breaker
- ✅ Prevents catastrophic losses
- ✅ Detects API/system failures
- ✅ Guards against hacks/unauthorized access

---

### 5️⃣ Exchange ↔ Internal Reconciliation Watchdog

**Purpose**: Prevent "ghost risk" from untracked positions.

**Implementation**: `bot/reconciliation_watchdog.py`

**Key Features**:
- Compares internal tracker vs exchange balances
- Detects:
  - Orphaned assets (exchange has, we don't track)
  - Phantom positions (we track, exchange doesn't have)
  - Size mismatches
  - Airdrops and forks
  - Partial fills not tracked
- Auto-adopt or liquidate (configurable)
- Periodic reconciliation (default hourly)

**Usage**:
```python
from bot.reconciliation_watchdog import get_reconciliation_watchdog

watchdog = get_reconciliation_watchdog(
    enable_auto_actions=False  # Alert only for now
)

# Run reconciliation
discrepancies = watchdog.reconcile_balances(
    exchange_balances={'BTC': 0.01, 'DOGE': 100.0},
    internal_positions={'BTC': 0.01},
    prices={'BTC': 50000.0, 'DOGE': 0.15},
    broker='coinbase'
)

# Get summary
summary = watchdog.get_reconciliation_summary()
print(f"Orphaned assets: {summary['orphaned_assets']}")
print(f"Phantom positions: {summary['phantom_positions']}")
```

**Configuration**:
```python
# Thresholds
dust_threshold_usd = 1.0           # Ignore < $1
auto_adopt_threshold_usd = 10.0    # Auto-adopt > $10
auto_liquidate_threshold_usd = 5.0 # Auto-liquidate $5-$10

# Reconciliation frequency
reconciliation_interval_minutes = 60  # Hourly

# Auto-actions (use with caution)
enable_auto_actions = False  # Default: alert only
```

**Benefits**:
- ✅ Prevents invisible risk
- ✅ Catches airdrops/forks automatically
- ✅ Identifies tracking bugs early
- ✅ Ensures accurate position reporting

---

### 6️⃣ Per-User Performance Attribution

**Purpose**: Track performance metrics for trust and debugging.

**Implementation**: Enhanced `bot/user_pnl_tracker.py`

**Key Features**:
- **Realized P&L**: Completed trades
- **Unrealized P&L**: Open positions (when prices available)
- **Fees Paid**: Total trading fees
- **Win Rate**: Percentage of winning trades
- **Average Hold Time**: Hours/minutes per trade
- **Daily/Weekly/Monthly** breakdowns
- Persistent JSON storage

**Usage**:
```python
from bot.user_pnl_tracker import get_user_pnl_tracker

tracker = get_user_pnl_tracker()

# Record a trade
tracker.record_trade(
    user_id="user_123",
    symbol="BTC-USD",
    side="sell",
    quantity=0.01,
    price=51000.0,
    size_usd=510.0,
    pnl_usd=10.0,
    pnl_pct=2.0,
    fee_usd=3.06,
    entry_time="2026-02-08T10:00:00",
    exit_time="2026-02-08T14:00:00"
)

# Get stats
stats = tracker.get_stats("user_123")
print(f"Win rate: {stats['win_rate']:.1f}%")
print(f"Total P&L: ${stats['total_pnl']:.2f}")
print(f"Fees paid: ${stats['total_fees']:.2f}")
print(f"Net P&L: ${stats['net_pnl_after_fees']:.2f}")
print(f"Avg hold time: {stats['avg_hold_time_hours']:.1f} hours")
```

**Tracked Metrics**:
```python
{
    'total_trades': 100,
    'completed_trades': 95,
    'open_positions': 5,
    'total_pnl': 150.0,
    'realized_pnl': 145.0,
    'unrealized_pnl': 5.0,
    'total_fees': 45.0,
    'net_pnl_after_fees': 105.0,
    'win_rate': 65.0,
    'avg_win': 5.0,
    'avg_loss': -3.0,
    'profit_factor': 1.67,
    'avg_hold_time_hours': 6.5,
    'daily_pnl': 10.0,
    'weekly_pnl': 45.0,
    'monthly_pnl': 150.0
}
```

**Benefits**:
- ✅ Builds trust through transparency
- ✅ Debugging power for strategy tuning
- ✅ Investor-ready metrics
- ✅ Performance trend analysis

---

### 7️⃣ High Signal-to-Noise Alerting

**Purpose**: Alert only on critical events, not spam.

**Implementation**: Enhanced `bot/monitoring_system.py`

**Key Features**:
- Alert **only** when needed:
  - Position cap breached
  - Forced cleanup triggered
  - Kill switch activated
  - Exchange desync detected
  - Drawdown > threshold
  - Reconciliation issues
  - Capital reservation full
- Multiple channels (console, file, webhook-ready)
- Alert levels: INFO, WARNING, CRITICAL, EMERGENCY
- Configurable thresholds

**Usage**:
```python
from bot.monitoring_system import MonitoringSystem, AlertType, AlertLevel

monitor = MonitoringSystem()

# Trigger critical alert
monitor.trigger_alert(
    alert_type=AlertType.KILL_SWITCH_ACTIVATED,
    level=AlertLevel.EMERGENCY,
    message="Kill switch activated: Daily loss limit exceeded",
    data={
        'daily_loss_pct': -12.5,
        'threshold': -10.0,
        'balance_change': -12.50
    }
)
```

**Alert Types** (New):
```python
AlertType.POSITION_CAP_BREACH       # Too many positions
AlertType.FORCED_CLEANUP_TRIGGERED  # Emergency position cleanup
AlertType.KILL_SWITCH_ACTIVATED     # Circuit breaker engaged
AlertType.EXCHANGE_DESYNC           # Reconciliation issue
AlertType.DRAWDOWN_THRESHOLD        # Max drawdown exceeded
AlertType.RECONCILIATION_ISSUE      # Orphaned/phantom assets
AlertType.CAPITAL_RESERVATION_FULL  # No capital for new trades
```

**Benefits**:
- ✅ Signal, not noise
- ✅ Immediate attention to critical issues
- ✅ Webhook-ready for Slack/Email/SMS
- ✅ Audit trail for incidents

---

## Integration Points

### Order Validation Pipeline

```python
from bot.minimum_notional_guard import should_block_order
from bot.validators.fee_validator import FeeValidator
from bot.capital_reservation_manager import can_open_position
from bot.kill_switch import get_kill_switch

def validate_order(size, price, symbol, balance, broker):
    """Complete order validation"""
    
    # 1. Check kill switch
    kill_switch = get_kill_switch()
    if kill_switch.is_active():
        return False, "Kill switch active - no new entries"
    
    # 2. Check minimum notional
    if should_block_order(size, price, broker, balance, symbol):
        return False, "Below minimum notional"
    
    # 3. Check fee ratio
    validator = FeeValidator()
    result = validator.validate_fee_to_position_ratio(
        size, price, broker, max_fee_pct=2.0, symbol=symbol
    )
    if result.level == ValidationLevel.ERROR:
        return False, f"Fee check failed: {result.message}"
    
    # 4. Check capital reservation
    can_open, msg, details = can_open_position(balance, size * price)
    if not can_open:
        return False, msg
    
    return True, "Validation passed"
```

### Position Manager Integration

```python
from bot.capital_reservation_manager import reserve_capital, release_capital

class PositionManager:
    def open_position(self, position_id, symbol, size_usd):
        """Open position with capital reservation"""
        # Reserve capital
        reserved = reserve_capital(position_id, size_usd, symbol)
        if not reserved:
            raise ValueError("Could not reserve capital")
        
        # ... open position logic ...
    
    def close_position(self, position_id):
        """Close position and release capital"""
        # ... close position logic ...
        
        # Release reserved capital
        released = release_capital(position_id)
        logger.info(f"Released ${released:.2f} capital")
```

### Auto-Trigger Integration

```python
from bot.kill_switch import get_auto_trigger

auto_trigger = get_auto_trigger()

# After every trade
def after_trade(pnl_usd, balance):
    is_winner = pnl_usd > 0
    
    # Check auto-triggers
    triggered = auto_trigger.auto_trigger_if_needed(
        current_balance=balance,
        last_trade_result=is_winner
    )
    
    if triggered:
        logger.critical("Auto-trigger activated kill switch")

# After API calls
def after_api_call(success):
    if success:
        auto_trigger.record_api_success()
    else:
        auto_trigger.record_api_error()
```

### Reconciliation Integration

```python
from bot.reconciliation_watchdog import get_reconciliation_watchdog

watchdog = get_reconciliation_watchdog()

# Periodic reconciliation (e.g., hourly)
def periodic_reconciliation(broker):
    if not watchdog.should_reconcile():
        return
    
    # Get balances from exchange
    exchange_balances = broker.get_balances()
    
    # Get internal positions
    internal_positions = position_manager.get_all_positions()
    
    # Get prices
    prices = broker.get_prices()
    
    # Reconcile
    discrepancies = watchdog.reconcile_balances(
        exchange_balances,
        internal_positions,
        prices,
        broker=broker.name
    )
    
    # Alert if issues found
    if discrepancies:
        monitor.trigger_alert(
            AlertType.RECONCILIATION_ISSUE,
            AlertLevel.WARNING,
            f"Found {len(discrepancies)} discrepancies",
            data={'discrepancies': len(discrepancies)}
        )
```

---

## Configuration

### Environment Variables

```bash
# Minimum Notional
NIJA_MIN_NOTIONAL_USD=5.0
NIJA_MIN_NOTIONAL_STRICT=true

# Fee Awareness
NIJA_MAX_FEE_PCT=2.0

# Capital Reservation
NIJA_SAFETY_BUFFER_PCT=20.0
NIJA_MIN_FREE_CAPITAL_USD=5.0

# Kill Switch Auto-Triggers
NIJA_MAX_DAILY_LOSS_PCT=10.0
NIJA_MAX_CONSECUTIVE_LOSSES=5
NIJA_MAX_API_ERRORS=10
NIJA_AUTO_TRIGGER_ENABLED=true

# Reconciliation
NIJA_RECONCILIATION_INTERVAL_MIN=60
NIJA_RECONCILIATION_AUTO_ACTIONS=false

# Alerting
NIJA_ALERT_WEBHOOK_URL=https://hooks.slack.com/...
```

### Python Configuration

```python
# config/risk_management.py

RISK_MANAGEMENT_CONFIG = {
    'minimum_notional': {
        'global_min_usd': 5.0,
        'strict_mode': True,
        'exchange_overrides': {
            'kraken': 10.0,
            'coinbase': 2.0
        }
    },
    'fee_awareness': {
        'max_fee_pct': 2.0,
        'warn_fee_pct': 1.5
    },
    'capital_reservation': {
        'safety_buffer_pct': 0.20,
        'min_free_capital_usd': 5.0
    },
    'kill_switch': {
        'auto_triggers': {
            'max_daily_loss_pct': 10.0,
            'max_consecutive_losses': 5,
            'max_api_errors': 10,
            'max_balance_delta_pct': 50.0
        },
        'enable_auto_trigger': True
    },
    'reconciliation': {
        'interval_minutes': 60,
        'dust_threshold_usd': 1.0,
        'auto_adopt_threshold_usd': 10.0,
        'enable_auto_actions': False
    },
    'alerting': {
        'channels': ['console', 'file'],
        'webhook_url': None  # Set to enable webhook alerts
    }
}
```

---

## Testing

### Unit Tests

Run individual module tests:

```bash
# Test minimum notional guard
python bot/minimum_notional_guard.py

# Test capital reservation
python bot/capital_reservation_manager.py

# Test reconciliation
python bot/reconciliation_watchdog.py

# Test kill switch
python bot/kill_switch.py
```

### Integration Tests

```python
# tests/test_risk_management_integration.py
import pytest
from bot.minimum_notional_guard import get_notional_guard
from bot.capital_reservation_manager import get_capital_reservation_manager
from bot.kill_switch import get_kill_switch, get_auto_trigger

def test_full_risk_management_flow():
    """Test complete risk management flow"""
    
    # Setup
    balance = 100.0
    position_size = 30.0
    
    # Test 1: Notional guard
    guard = get_notional_guard()
    is_valid, error, details = guard.validate_order_notional(
        size=0.006, price=5000.0, balance=balance
    )
    assert is_valid, "Should pass notional check"
    
    # Test 2: Capital reservation
    manager = get_capital_reservation_manager()
    can_open, msg, details = manager.can_open_position(
        balance, position_size
    )
    assert can_open, "Should have enough capital"
    
    # Reserve capital
    reserved = manager.reserve_capital("pos1", position_size, "BTC-USD")
    assert reserved, "Should reserve successfully"
    
    # Test 3: Kill switch (should allow initially)
    kill_switch = get_kill_switch()
    assert not kill_switch.is_active(), "Kill switch should be inactive"
    
    # Test 4: Auto-trigger (simulate losses)
    auto_trigger = get_auto_trigger()
    for i in range(5):
        reason = auto_trigger.record_trade_result(is_winner=False)
    
    # Should trigger after 5 consecutive losses
    assert kill_switch.is_active(), "Kill switch should activate"
    
    # Cleanup
    kill_switch.deactivate("Test complete")
```

---

## Monitoring & Maintenance

### Daily Checks

```bash
# Check kill switch status
python -c "from bot.kill_switch import get_kill_switch; print(get_kill_switch().get_status())"

# Check capital reservation
python -c "from bot.capital_reservation_manager import get_capital_reservation_manager; print(get_capital_reservation_manager().get_reservation_summary())"

# Check reconciliation
python -c "from bot.reconciliation_watchdog import get_reconciliation_watchdog; print(get_reconciliation_watchdog().get_reconciliation_summary())"
```

### Logs to Monitor

```
✅ Minimum Notional Guard initialized
✅ Capital Reservation Manager initialized
✅ Kill Switch Auto-Trigger initialized
✅ Reconciliation Watchdog initialized

⚠️ Order below minimum notional (warnings)
❌ BLOCKING ORDER (errors)
🚨 Kill switch activated (critical)
🚨 Discrepancy detected (warnings)
```

---

## Best Practices

1. **Start Conservative**: Use strict settings initially
   - `min_notional_usd = 10.0` for small accounts
   - `max_fee_pct = 1.5` for better profitability
   - `safety_buffer_pct = 0.30` (30%) for more safety

2. **Monitor Auto-Triggers**: Review why kill switch activates
   - Check logs for activation reasons
   - Adjust thresholds if too sensitive
   - Investigate root causes

3. **Review Reconciliation**: Check weekly for patterns
   - Orphaned assets → Exchange issue or tracking bug
   - Phantom positions → Exit logic bug
   - Size mismatches → Partial fill handling

4. **Track Performance**: Use PnL metrics for decisions
   - Low win rate → Strategy issue
   - High fees → Position sizes too small
   - Long hold times → Exit logic too slow

5. **Test Configuration Changes**: Never change in production directly
   - Test in paper trading first
   - Gradually roll out changes
   - Monitor for unexpected behavior

---

## Troubleshooting

### Issue: Too many orders blocked

**Symptoms**: Most orders fail minimum notional check

**Solutions**:
1. Lower `min_notional_usd` for your account size
2. Increase position sizing logic
3. Fund account to larger balance

### Issue: Kill switch triggers too often

**Symptoms**: Frequent auto-trigger activations

**Solutions**:
1. Increase `max_daily_loss_pct` threshold
2. Increase `max_consecutive_losses` threshold
3. Review strategy for systematic issues

### Issue: Reconciliation shows many discrepancies

**Symptoms**: Constant orphaned assets or phantom positions

**Solutions**:
1. Check position tracking logic
2. Verify exit order execution
3. Review partial fill handling
4. Enable auto-adopt for known airdrops

### Issue: Capital reservation prevents trading

**Symptoms**: "Cannot open position" errors

**Solutions**:
1. Reduce `safety_buffer_pct`
2. Close some existing positions
3. Increase account balance
4. Check for stuck reservations

---

## What You Do NOT Need

Per the original requirements, focus on **discipline, not aggression**:

❌ More indicators  
❌ More coins  
❌ More leverage  
❌ More speed  
❌ More AI buzzwords  

✅ Better risk management  
✅ Capital efficiency  
✅ Structural safety  
✅ Trust and transparency  

---

## Support

For issues or questions:
1. Check logs first
2. Review this guide
3. Test in isolation
4. Report with full context

---

**Version**: 1.0  
**Date**: February 8, 2026  
**Author**: NIJA Trading Systems
