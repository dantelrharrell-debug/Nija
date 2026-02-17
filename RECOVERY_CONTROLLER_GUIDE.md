# NIJA Recovery Controller Guide

## Overview

The **RecoveryController** is NIJA's capital-first, authoritative safety layer that sits above all other systems. It has the power to halt all trading operations when capital safety is uncertain.

This is **NOT** just another safety check - it is the **SINGLE SOURCE OF TRUTH** for whether trading is allowed.

## Architecture Position

```
┌─────────────────────────────────────────────────────────┐
│                  RECOVERY CONTROLLER                     │
│         (Capital-First, Authoritative Layer)             │
│  ┌──────────────────────────────────────────────────┐  │
│  │  • Finite State Machine (FSM)                    │  │
│  │  • Capital-Safety Matrix                         │  │
│  │  • trading_enabled flag                          │  │
│  │  • safe_mode flag                                │  │
│  │  • State transition validation                   │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                   ↓                   ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Trading    │  │  Execution   │  │     Risk     │
│   Strategy   │  │    Engine    │  │   Manager    │
└──────────────┘  └──────────────┘  └──────────────┘
```

## Core Components

### 1. Finite State Machine (FSM)

The FSM maintains system state with deterministic transitions:

**States:**
- `NORMAL` - System operating normally, all features enabled
- `DEGRADED` - Minor issues detected, reduced trading activity
- `RECOVERY` - Recovering from failure, limited operations
- `SAFE_MODE` - Capital protection mode, exits only, no entries
- `EMERGENCY_HALT` - Complete trading halt, no operations allowed

**Valid State Transitions:**
```
NORMAL → DEGRADED, SAFE_MODE, EMERGENCY_HALT
DEGRADED → NORMAL, RECOVERY, SAFE_MODE, EMERGENCY_HALT
RECOVERY → NORMAL, DEGRADED, SAFE_MODE, EMERGENCY_HALT
SAFE_MODE → RECOVERY, EMERGENCY_HALT
EMERGENCY_HALT → RECOVERY (manual recovery only)
```

### 2. Capital-Safety Matrix

The matrix assesses capital risk based on:
- **Balance remaining** (% of initial capital)
- **Position count** (number of open positions)
- **Drawdown** (% from peak capital)

**Safety Levels:**
- `SAFE` - Capital is safe, normal operations
- `CAUTION` - Approaching risk limits, reduce activity
- `WARNING` - Risk limits breached, defensive mode
- `DANGER` - Significant risk, exit positions
- `CRITICAL` - Emergency, halt all trading

**Matrix Thresholds:**
```
Balance% | Max Positions | Max Drawdown | Safety Level
---------|---------------|--------------|-------------
90%      | 100           | 10%          | SAFE
80%      | 50            | 15%          | SAFE
70%      | 30            | 20%          | CAUTION
60%      | 20            | 25%          | WARNING
50%      | 10            | 30%          | DANGER
<50%     | Any           | >40%         | CRITICAL
```

**Override Rules:**
- Balance < 50% → DANGER (minimum)
- Balance < 30% → CRITICAL
- Drawdown > 40% → CRITICAL

### 3. Trading Permission Logic

The `can_trade(operation)` method is the **AUTHORITATIVE CHECK** for all trading:

```python
# Check before entry
can_trade, reason = recovery_controller.can_trade("entry")
if not can_trade:
    # Entry blocked
    return None

# Check before exit
can_trade, reason = recovery_controller.can_trade("exit")
if not can_trade:
    # Exit blocked (only in EMERGENCY_HALT)
    return False
```

**Permission Rules by State:**

| State          | Entries | Exits | Modify |
|----------------|---------|-------|--------|
| NORMAL         | ✅      | ✅    | ✅     |
| DEGRADED       | ✅*     | ✅    | ✅     |
| RECOVERY       | ❌      | ✅    | ⚠️     |
| SAFE_MODE      | ❌      | ✅    | ⚠️     |
| EMERGENCY_HALT | ❌      | ❌    | ❌     |

*Subject to capital safety level

**Capital Safety Restrictions:**
- `SAFE/CAUTION` - All operations allowed
- `WARNING` - Entries reduced/blocked
- `DANGER` - Entries blocked, exits only
- `CRITICAL` - Auto-transition to EMERGENCY_HALT

## Integration Points

### 1. Execution Engine Integration

The RecoveryController is checked **FIRST** before any order execution:

```python
# In execute_entry()
if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller:
    recovery_controller = get_recovery_controller()
    can_trade, reason = recovery_controller.can_trade("entry")
    
    if not can_trade:
        logger.error("🛡️ RECOVERY CONTROLLER BLOCKED ENTRY")
        return None

# In execute_exit()
if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller:
    recovery_controller = get_recovery_controller()
    can_trade, reason = recovery_controller.can_trade("exit")
    
    if not can_trade:
        logger.error("🛡️ RECOVERY CONTROLLER BLOCKED EXIT")
        return False
```

### 2. Trading Strategy Integration

The strategy consults the RecoveryController at the start of each cycle:

```python
# In run_cycle()
if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller:
    recovery_controller = get_recovery_controller()
    
    # Update capital safety with current balance
    recovery_controller.assess_capital_safety(
        current_balance=current_balance,
        position_count=position_count
    )
    
    # Check if entries allowed
    can_trade_entry, reason = recovery_controller.can_trade("entry")
    if not can_trade_entry:
        # Force position-management-only mode
        user_mode = True
```

### 3. Safety Controller Integration

The RecoveryController works alongside the existing SafetyController:

```python
# SafetyController handles:
- Cold start safety
- App Store mode
- Emergency stop file
- Trading mode states

# RecoveryController handles:
- Capital safety assessment
- State machine management
- Failure recovery
- Authoritative trading permission
```

## Usage Examples

### Basic Usage

```python
from bot.recovery_controller import get_recovery_controller

# Get the global singleton
controller = get_recovery_controller()

# Check if trading is allowed
can_trade, reason = controller.can_trade("entry")
if can_trade:
    # Execute trade
    pass
else:
    # Trade blocked
    logger.error(f"Trade blocked: {reason}")
```

### Capital Safety Assessment

```python
# Update capital safety (should be called regularly)
safety_level = controller.assess_capital_safety(
    current_balance=9500.0,
    initial_balance=10000.0,
    position_count=5,
    open_pnl=150.0
)

# Check safety level
if safety_level == CapitalSafetyLevel.DANGER:
    # Take defensive action
    logger.warning("Capital at risk - reducing exposure")
```

### Manual State Transitions

```python
# Transition to safe mode
success = controller.transition_to(
    FailureState.SAFE_MODE,
    "Manual intervention - market volatility"
)

# Transition back to normal
success = controller.transition_to(
    FailureState.RECOVERY,
    "Beginning recovery"
)

success = controller.transition_to(
    FailureState.NORMAL,
    "System recovered"
)
```

### Enable/Disable Trading

```python
# Enable trading
controller.enable_trading("System startup")

# Disable trading
controller.disable_trading("Manual shutdown")

# Check if enabled
if controller.is_trading_enabled:
    logger.info("Trading is enabled")
```

### Failure Recording

```python
# Record a failure
controller.record_failure(
    failure_type="broker_error",
    details="Connection timeout to Coinbase API"
)

# After multiple failures, state automatically transitions:
# 2 failures → DEGRADED
# 5 failures → SAFE_MODE
# 10 failures → EMERGENCY_HALT

# Reset failures after fixing issues
controller.reset_failures()
```

### Status Monitoring

```python
# Get comprehensive status
status = controller.get_status()

print(f"State: {status['state']}")
print(f"Trading Enabled: {status['trading_enabled']}")
print(f"Safe Mode: {status['safe_mode']}")
print(f"Capital Safety: {status['capital_safety_level']}")
print(f"Failure Count: {status['failure_count']}")
print(f"Current Balance: {status['capital']['current']}")
print(f"Drawdown: {status['capital']['drawdown_pct']:.2f}%")
```

## State Persistence

The RecoveryController automatically persists state to `.nija_recovery_state.json`:

```json
{
  "current_state": "normal",
  "trading_enabled": true,
  "safe_mode": false,
  "capital_safety_level": "safe",
  "failure_count": 0,
  "initial_capital": 10000.0,
  "current_capital": 9800.0,
  "peak_capital": 10200.0,
  "current_drawdown_pct": 3.92,
  "position_count": 5,
  "history": [
    {
      "timestamp": "2026-02-17T21:00:00",
      "state": "normal",
      "trading_enabled": true,
      "reason": "System initialized"
    }
  ]
}
```

## Safety Guarantees

The RecoveryController provides the following guarantees:

1. **No Trading Without Permission**: All trading operations MUST check `can_trade()` first
2. **State Transitions Are Validated**: Invalid transitions are rejected
3. **Capital Safety Is Enforced**: Automatic transitions based on capital levels
4. **State Is Persistent**: Survives restarts and crashes
5. **Single Source of Truth**: One controller instance per system
6. **Thread-Safe**: All operations are protected by locks
7. **Automatic Recovery**: Failed state transitions don't leave system in undefined state

## Emergency Procedures

### Emergency Halt Activation

```python
# Activate emergency halt
controller.transition_to(
    FailureState.EMERGENCY_HALT,
    "Critical capital loss detected"
)

# All trading stops immediately:
# - No new entries
# - No exits (positions frozen)
# - No modifications
# - Only manual recovery possible
```

### Manual Recovery from Emergency Halt

```python
# Step 1: Assess the situation
status = controller.get_status()
print(f"Capital: {status['capital']}")
print(f"Drawdown: {status['capital']['drawdown_pct']:.2f}%")

# Step 2: Reset failures if appropriate
controller.reset_failures()

# Step 3: Transition to recovery
controller.transition_to(
    FailureState.RECOVERY,
    "Manual recovery initiated - issues resolved"
)

# Step 4: Monitor and transition to normal when ready
# (After verifying system stability)
controller.transition_to(
    FailureState.NORMAL,
    "Recovery complete - resuming normal operations"
)

# Step 5: Re-enable trading
controller.enable_trading("Recovery validated")
```

## Testing

Run the comprehensive test suite:

```bash
cd /home/runner/work/Nija/Nija
python -m unittest bot.tests.test_recovery_controller -v
```

**Test Coverage:**
- FSM state transitions (valid and invalid)
- Capital safety assessment
- Trading permission logic
- Failure recording and recovery
- State persistence
- Global singleton pattern

## Best Practices

1. **Always Check Before Trading**
   ```python
   can_trade, reason = controller.can_trade("entry")
   if not can_trade:
       return None  # Don't proceed
   ```

2. **Update Capital Regularly**
   ```python
   # Update at start of each trading cycle
   controller.assess_capital_safety(
       current_balance=balance,
       position_count=len(positions)
   )
   ```

3. **Record All Failures**
   ```python
   # Record failures immediately
   try:
       # Trading operation
       pass
   except Exception as e:
       controller.record_failure("operation_name", str(e))
   ```

4. **Monitor State Changes**
   ```python
   # Log state transitions
   status = controller.get_status()
   logger.info(f"Recovery Controller: {status['state']}")
   ```

5. **Don't Bypass the Controller**
   - Never place orders without checking `can_trade()`
   - Don't modify state files directly
   - Let the controller manage state transitions

## Troubleshooting

### Trading is Blocked

```python
# Check why trading is blocked
can_trade, reason = controller.can_trade("entry")
print(f"Blocked: {reason}")

# Check current state
status = controller.get_status()
print(f"State: {status['state']}")
print(f"Capital Safety: {status['capital_safety_level']}")
print(f"Trading Enabled: {status['trading_enabled']}")
```

### Stuck in Emergency Halt

```python
# Review the failure history
status = controller.get_status()
for event in status.get('history', [])[-10:]:
    print(event)

# Manual recovery (see Emergency Procedures above)
```

### Capital Safety Warnings

```python
# Check capital metrics
status = controller.get_status()
capital = status['capital']

print(f"Initial: ${capital['initial']:.2f}")
print(f"Current: ${capital['current']:.2f}")
print(f"Peak: ${capital['peak']:.2f}")
print(f"Drawdown: {capital['drawdown_pct']:.2f}%")
print(f"Positions: {capital['position_count']}")

# Adjust position sizing or close positions
```

## FAQ

**Q: Can I disable the RecoveryController?**
A: No. It's designed to be always-on for capital protection. If it's not available, a warning is logged but the system continues with reduced safety.

**Q: What happens if the controller fails?**
A: The controller uses defensive programming with try-except blocks. If it fails, it logs errors but doesn't crash the system. However, trading may be blocked until the issue is resolved.

**Q: Can I have multiple controllers?**
A: No. The system uses a singleton pattern to ensure one source of truth. Use `get_recovery_controller()` to access the global instance.

**Q: How often should I update capital safety?**
A: At the start of each trading cycle (every 2-5 minutes typically). The controller tracks peak capital and drawdown automatically.

**Q: Can the controller place or close orders?**
A: No. The controller only provides permission checks. The execution engine and strategy still handle actual order placement.

**Q: What's the difference between SAFE_MODE and EMERGENCY_HALT?**
A: 
- `SAFE_MODE`: Allows exits, blocks entries
- `EMERGENCY_HALT`: Blocks everything, including exits

## Version History

- **v1.0.0** (Feb 2026) - Initial implementation
  - FSM with 5 states
  - Capital-safety matrix
  - Integration with execution engine and strategy
  - Comprehensive test suite (18 tests)
  - State persistence
  - Global singleton pattern

## Support

For issues or questions:
1. Check the test suite for usage examples
2. Review the inline documentation in `recovery_controller.py`
3. Check logs for state transitions and blocked operations
4. Use `get_status()` to debug current state

## License

Part of the NIJA Trading System.
© 2026 NIJA Trading Systems. All rights reserved.
