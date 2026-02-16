# Execution Layer Hardening Documentation

## Overview

This document describes the execution-layer hardening system implemented to prevent unprofitable small positions and excessive position counts in NIJA.

## Critical Design Principle

**THE EXECUTION LAYER IS THE LAW**

All hardening controls are enforced at the execution layer (`broker_manager.py`) and CANNOT be bypassed by:
- Strategy layer
- Signal engine
- Copy trading systems
- Broker adapters

## Requirements Enforced

### 1. User Position Cap (Match Platform Cap)

**Enforcement:** `execution_position_cap_enforcer.py`

Tier-aware position limits:
- STARTER ($50-$99): 1 position
- SAVER ($100-$249): 1 position
- INVESTOR ($250-$999): 3 positions
- INCOME ($1,000-$4,999): 5 positions
- LIVABLE ($5,000-$24,999): 6 positions
- BALLER ($25,000+): 8 positions

**Implementation:**
```python
can_open, reason, details = enforcer.can_open_new_position(
    current_position_count=len(positions),
    balance=account_balance,
    user_id=user_id
)
```

### 2. Minimum Per-Position Allocation (5-10% of Account)

**Enforcement:** `execution_minimum_position_gate.py`

Minimum position sizes by tier:
- STARTER: $10 USD
- SAVER: $10 USD
- INVESTOR: $20 USD
- INCOME: $50 USD (updated from $30)
- LIVABLE: $50 USD
- BALLER: $100 USD

Additionally enforces 5% minimum allocation to prevent spreading capital too thin.

**Implementation:**
```python
is_valid, reason, details = gate.validate_position_size(
    position_size_usd=quantity,
    balance=account_balance,
    symbol=symbol,
    user_id=user_id
)
```

### 3. Block New Entries Below $X Minimum

**Enforcement:** `execution_minimum_position_gate.py` (same module as #2)

Absolute minimums prevent positions too small to be profitable after fees.

### 4. Consolidate Dust Positions

**Enforcement:** `execution_layer_hardening.py` + `dust_prevention_engine.py`

Prevents creation of new dust positions (< $1 USD). Existing dust prevention engine auto-closes dust positions.

**Implementation:**
```python
if position_size_usd < DUST_THRESHOLD_USD:
    # Block this order
    return False, "Would create dust position"
```

### 5. Disable Trading if Average Position < Fee Threshold

**Enforcement:** `execution_average_position_monitor.py`

Monitors average position size across all open positions:
- Fee threshold: $5 USD (Coinbase)
- Minimum average: $7.50 USD (1.5x fee threshold)

Blocks new positions that would drag average below profitability threshold.

**Implementation:**
```python
can_open, reason, details = monitor.can_open_new_position(
    positions=current_positions,
    new_position_size=quantity,
    symbol=symbol,
    user_id=user_id
)
```

## Integration Point

All checks are integrated in `broker_manager.py` → `CoinbaseBroker.place_market_order()`:

```python
# After balance checks, before API call
if EXECUTION_HARDENING_AVAILABLE and side.lower() == 'buy' and not force_liquidate:
    hardening = get_execution_layer_hardening(broker_type='coinbase')
    
    is_valid, error_reason, validation_details = hardening.validate_order_hardening(
        symbol=symbol,
        side=side,
        position_size_usd=quantity,
        balance=account_balance,
        current_positions=current_positions,
        user_id=user_id,
        force_liquidate=force_liquidate
    )
    
    if not is_valid:
        # Block order and return error
        return {
            "status": "unfilled",
            "error": "HARDENING_ENFORCEMENT",
            "message": error_reason,
            ...
        }
```

## Bypass Rules

### SELL Orders
SELL orders **ALWAYS** bypass hardening checks. This ensures:
- Stop-loss exits always execute
- Emergency liquidation always works
- Losing positions can always be closed
- Capital preservation is never blocked

### Emergency Liquidation
When `force_liquidate=True`, ALL checks are bypassed for emergency exits.

### App Store Mode
App Store Mode check happens BEFORE hardening (Layer 0) and blocks all real orders.

## Execution Flow

```
User Signal
    ↓
Strategy Decision (can be bypassed)
    ↓
Signal Engine (can be bypassed)
    ↓
Broker Adapter (can be bypassed)
    ↓
broker_manager.place_market_order()
    ↓
[LAYER 0] App Store Mode Check
    ↓
[LAYER 1] Symbol Validation
    ↓
[LAYER 2] Global Buy Guard
    ↓
[LAYER 3] Balance Validation
    ↓
[LAYER 4] EXECUTION HARDENING ← THE LAW
    ├─ Position Cap Check
    ├─ Minimum Size Check
    ├─ Average Position Monitor
    └─ Dust Prevention
    ↓
Broker API Call (only if all checks pass)
```

## Error Handling

When hardening blocks an order, comprehensive logging is produced:

```
============================================================
🛡️ EXECUTION LAYER HARDENING: ORDER BLOCKED
============================================================
Symbol: BTC-USD
Side: BUY
Position Size: $3.00
Balance: $100.00
Current Positions: 0
Reason: Position size $3.00 below tier minimum $10.00

This order was blocked to prevent:
  • Excessive position count (exceeding tier limits)
  • Position sizes too small to be profitable
  • Dust accumulation and fee bleeding
  • Average position size below profitability threshold

To fix: Close small positions or increase position size
============================================================
```

## Testing

All modules include self-tests:

```bash
# Test individual modules
python bot/execution_position_cap_enforcer.py
python bot/execution_minimum_position_gate.py
python bot/execution_average_position_monitor.py
python bot/execution_layer_hardening.py

# Integration test
python test_execution_hardening_integration.py
```

## Monitoring

Check hardening status at runtime:

```python
from bot.execution_layer_hardening import get_execution_layer_hardening

hardening = get_execution_layer_hardening()
status = hardening.get_hardening_status()

print(f"Fully Operational: {status['fully_operational']}")
print(f"Position Cap: {status['position_cap_enabled']}")
print(f"Minimum Size: {status['minimum_size_enabled']}")
print(f"Average Monitor: {status['average_monitor_enabled']}")
print(f"Dust Prevention: {status['dust_prevention_enabled']}")
```

## Security

- ✅ CodeQL scan passed with 0 alerts
- ✅ No vulnerabilities introduced
- ✅ Comprehensive error logging for audit trail
- ✅ Cannot be bypassed (execution layer enforcement)
- ✅ Safe failure mode (allows order if hardening crashes, but logs error)

## Maintenance

When adding new brokers, update:
1. `execution_average_position_monitor.py` - Add fee threshold for new broker
2. `execution_layer_hardening.py` - Pass correct broker_type
3. Integration in new broker's `place_market_order()` method

When changing tier configuration:
1. Update `bot/tier_config.py`
2. Enforcement modules automatically use new tier limits
3. No changes needed to hardening modules

## Future Enhancements

Potential improvements:
- Add webhook notifications when orders are blocked
- Dashboard showing hardening metrics
- Historical tracking of blocked orders
- Per-user hardening configuration
- Dynamic threshold adjustment based on market conditions
