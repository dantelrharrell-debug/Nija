# NIJA Institutional System - Quick Start Guide

## 🚀 Quick Start (5 Minutes)

### Step 1: Import the Integration

```python
from institutional_integration import get_institutional_integration, is_institutional_mode_available

# Check if all systems are available
if not is_institutional_mode_available():
    print("⚠️ Some institutional systems unavailable - using fallback mode")
```

### Step 2: Initialize with Your Balance

```python
# Initialize with current account balance
integration = get_institutional_integration(
    balance=5000.0,
    broker_name="coinbase"
)

# System automatically:
# - Detects your capital tier (MICRO/GROWTH/PRO/INSTITUTIONAL)
# - Sets appropriate position limits
# - Configures risk parameters
# - Initializes audit logging
```

### Step 3: Validate Entries

```python
# Before executing any trade, validate it
allowed, reason, audit_id = integration.validate_entry_comprehensive(
    symbol="BTC-USD",
    signal_type="LONG",
    entry_score=4.2,          # Your entry score (0-5)
    confidence=0.75,          # Your confidence (0-1)
    signal_contributions={    # Which indicators contributed
        'rsi': 2.5,
        'vwap': 1.8,
        'macd': 1.2,
        'volume': 0.8
    },
    primary_trigger="rsi",    # Primary entry trigger
    price=96000.0,            # Current price
    proposed_size_usd=100.0,  # Proposed position size
    stop_loss_price=95000.0,  # Stop loss price
    adx=25.0,                 # Optional: ADX value
    rsi=35.0,                 # Optional: RSI value
    volume_24h=1000000.0      # Optional: 24h volume
)

if allowed:
    print(f"✅ Entry approved - Audit ID: {audit_id}")
    # Execute your trade
else:
    print(f"❌ Entry rejected: {reason}")
    # Don't execute trade
```

### Step 4: Track Position Lifecycle

```python
# After trade executes
if allowed:
    integration.register_position_opened(
        symbol="BTC-USD",
        size_usd=100.0,
        entry_price=96000.0,
        side="LONG",
        stop_loss=95000.0,
        audit_id=audit_id  # Links to entry audit
    )

# In your monitoring loop (update position prices)
integration.update_position_price("BTC-USD", 97000.0)

# When trade closes
integration.register_position_closed(
    symbol="BTC-USD",
    exit_price=97000.0,
    pnl_usd=10.0,
    audit_id=audit_id  # Links outcome to entry
)
```

### Step 5: Monitor Health

```python
# Check for zombie positions that need force-closing
zombies = integration.get_positions_to_force_close()
if zombies:
    print(f"⚠️ Force close recommended: {zombies}")

# Check if volatility spike requires position reduction
should_reduce, target_count = integration.should_reduce_positions()
if should_reduce:
    print(f"⚠️ Reduce positions to {target_count} due to volatility")

# Update balance regularly (auto tier transitions)
integration.update_balance(new_balance)
```

---

## 📊 Daily Summary

```python
# Print daily summary (call once per day)
integration.print_daily_summary()
```

**Output**:
```
============================================================
📊 DAILY ENTRY AUDIT SUMMARY - 2026-02-18
============================================================
Total Signals: 45
Accepted: 32 (71.1%)
Rejected: 13 (28.9%)

Top Rejection Reasons:
  TIER_MAX_POSITIONS: 5
  DRAWDOWN_LOCK: 4
  TIER_REQUIREMENTS: 2
  DUPLICATE_ENTRY: 2
============================================================

============================================================
🏗️ POSITION ARCHITECTURE STATUS
============================================================
Tier: GROWTH | Balance: $5000.00
Positions: 3/5 (60%)
Exposure: 45.2% | Reserve: 54.8%

Position Health:
  BTC-USD: ACTIVE | Health: 85 | Age: 2.3h
  ETH-USD: ACTIVE | Health: 78 | Age: 4.1h
  SOL-USD: STALE | Health: 62 | Age: 14.5h
============================================================

============================================================
💰 CAPITAL TIER STATUS
============================================================
Current Tier: GROWTH
Balance: $5000.00
Tier Range: $500-$5,000
Tier Progress: 90%
Next Milestone: $5,000 (100.0%)
Milestones: 4/11

Tier Configuration:
  Max Positions: 3-5
  Risk per Trade: 1.00%-2.00%
  Aggression: 60%
  Max Daily Trades: 15
  Daily Loss Limit: 4.0%
  High Confidence Required: True
  Stability Priority: False
============================================================
```

---

## 🎯 Common Use Cases

### Use Case 1: Basic Entry Validation

```python
# Minimal integration - just validate entries
from institutional_integration import get_institutional_integration

integration = get_institutional_integration(balance, broker)

def should_enter_trade(symbol, signal_data):
    allowed, reason, audit_id = integration.validate_entry_comprehensive(
        symbol=symbol,
        signal_type=signal_data['type'],
        entry_score=signal_data['score'],
        confidence=signal_data['confidence'],
        signal_contributions=signal_data['contributions'],
        primary_trigger=signal_data['trigger'],
        price=signal_data['price'],
        proposed_size_usd=calculate_size(),
        stop_loss_price=calculate_stop_loss()
    )
    
    return allowed, reason, audit_id
```

### Use Case 2: Check Your Current Tier

```python
context = integration.get_context()

print(f"Tier: {context.tier_level}")
print(f"Max Positions: {context.max_positions}")
print(f"Current Positions: {context.current_positions}")
print(f"Available Capital: ${context.available_capital:.2f}")
print(f"Exposure: {context.total_exposure_pct:.1%}")

if context.drawdown_locked:
    print(f"⚠️ TRADING HALTED: {context.drawdown_reason}")
```

### Use Case 3: Calculate Position Size

```python
# Let the tier system calculate optimal position size
position_size = integration.calculate_position_size(
    signal_confidence=0.75  # Your signal confidence
)

print(f"Recommended position size: ${position_size:.2f}")
```

### Use Case 4: Monitor Position Health

```python
# In your main loop
while trading:
    # Update all position prices
    for symbol, price in get_current_prices().items():
        integration.update_position_price(symbol, price)
    
    # Check for problems
    zombies = integration.get_positions_to_force_close()
    for zombie in zombies:
        print(f"🧟 Force closing zombie position: {zombie}")
        close_position(zombie)
    
    # Check volatility
    should_reduce, target = integration.should_reduce_positions()
    if should_reduce:
        print(f"📉 Volatility spike - reducing to {target} positions")
        reduce_positions(target)
    
    time.sleep(60)  # Check every minute
```

### Use Case 5: Analytics & Reporting

```python
from entry_audit_system import get_entry_audit_system

audit = get_entry_audit_system()

# Get statistics
stats = audit.get_stats_summary()

print(f"Acceptance Rate: {stats['acceptance_rate']:.1%}")
print(f"Total Signals: {stats['total_signals']}")

# Win rates by trigger
for trigger, data in stats['win_rates_by_trigger'].items():
    print(f"{trigger}: {data['win_rate']:.1%} win rate "
          f"({data['wins']}/{data['total_trades']} trades)")

# Top rejection reasons
top_rejections = audit.get_top_rejection_reasons(5)
for reason, count in top_rejections:
    print(f"{reason}: {count} rejections")
```

---

## ⚙️ Configuration

### Capital Tiers

The system automatically assigns you to a tier based on balance:

| Balance | Tier | Max Positions | Risk/Trade |
|---------|------|--------------|------------|
| $50-$500 | MICRO | 1-2 | 2-3% |
| $500-$5k | GROWTH | 3-5 | 1-2% |
| $5k-$50k | PRO | 5-10 | 0.5-1% |
| $50k-$250k | INSTITUTIONAL | 10-20 | 0.25-0.5% |

**Automatic tier transitions** happen when your balance crosses tier boundaries.

### Exposure Limits (Hard-Coded)

```python
max_total_exposure = 80%    # Max of account in positions
capital_reserve = 20%        # Min idle buffer
max_per_symbol = 15%         # Max single position size
```

### Drawdown Protection (Hard-Coded)

```python
daily_max_loss = 5%     # Trading halts for 24h
weekly_max_loss = 10%   # Trading halts for 7 days
```

### Position Health Thresholds

```python
stale_threshold = 12 hours    # No price movement
aged_threshold = 24 hours     # Position too old
zombie = stale + aged + underwater
```

---

## 🔍 Troubleshooting

### "Institutional mode not available"

One or more systems couldn't be imported. Check:
- `entry_audit_system.py` exists
- `position_architecture.py` exists
- `capital_tier_scaling.py` exists
- `institutional_integration.py` exists

**Fallback**: System will work without institutional features.

### "Entry rejected: TIER_MAX_POSITIONS"

You're at your tier's maximum position count. Options:
1. Wait for a position to close
2. Force close a position
3. Increase capital to upgrade tier

### "Entry rejected: DRAWDOWN_LOCK"

You've hit daily (5%) or weekly (10%) loss limit. Options:
1. Wait for lock to expire (24h or 7d)
2. Review strategy to prevent losses
3. No override available (capital protection)

### "Entry rejected: DUPLICATE_ENTRY"

You attempted to enter the same symbol within 5 minutes. Options:
1. Wait 5 minutes
2. This prevents double-entry accidents
3. No override available (safety feature)

### "Entry rejected: Insufficient reserve buffer"

Your positions would exceed 80% exposure. Options:
1. Close a position to free capital
2. Use smaller position size
3. Reserve buffer is mandatory (risk management)

---

## 📈 Best Practices

### 1. Always Validate Before Executing

```python
# ✅ GOOD
allowed, reason, audit_id = integration.validate_entry_comprehensive(...)
if allowed:
    execute_trade()

# ❌ BAD
execute_trade()  # No validation
```

### 2. Track Full Position Lifecycle

```python
# ✅ GOOD - Track open, updates, close
integration.register_position_opened(...)
integration.update_position_price(...)  # Regularly
integration.register_position_closed(...)

# ❌ BAD - Only track open
integration.register_position_opened(...)
# No updates or close tracking
```

### 3. Update Balance Regularly

```python
# ✅ GOOD - Update after significant changes
def on_position_close(pnl):
    new_balance = get_current_balance()
    integration.update_balance(new_balance)  # Auto tier transitions

# ❌ BAD - Never update
# Tier system won't know you've grown capital
```

### 4. Monitor Health Metrics

```python
# ✅ GOOD - Check regularly
zombies = integration.get_positions_to_force_close()
should_reduce, target = integration.should_reduce_positions()

# ❌ BAD - Ignore health warnings
# Zombie positions drain capital
```

### 5. Review Daily Summary

```python
# ✅ GOOD - Review analytics daily
integration.print_daily_summary()
# Understand why entries are rejected
# Track win rates by trigger type

# ❌ BAD - Never review
# Miss opportunity to improve strategy
```

---

## 🎉 You're Ready!

The institutional system is now protecting your capital and scaling with you.

**Key Takeaways**:
1. ✅ Validate every entry
2. ✅ Track full position lifecycle  
3. ✅ Monitor position health
4. ✅ Update balance regularly
5. ✅ Review daily analytics

**Questions?** See `INSTITUTIONAL_ARCHITECTURE.md` for detailed documentation.

**Happy Trading! 🚀**
