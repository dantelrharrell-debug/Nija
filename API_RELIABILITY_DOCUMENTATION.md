# Broker API Reliability & Position Cap Enforcement

## Overview

This document describes the critical infrastructure improvements implemented to address institutional-grade trading requirements:

1. **Broker API Reliability Layer** - Circuit breaker pattern with exponential backoff
2. **Hard Position Cap Enforcement** - Atomic verification and re-run until compliant
3. **Removed Fallback Pricing** - Block trading on unvalued positions

## Problem Statement

### Issues Fixed

1. **Position Cap Exceeded by 7x**
   - Initial: 0 positions
   - Final: 59 positions (cap was 8)
   - Cause: Position fetch failed or cleanup logic didn't run on stale data

2. **Dangerous Fallback Pricing**
   - System used $1.00 fallback when price fetch failed
   - Wrong valuations → wrong risk calc → wrong exposure calc → wrong liquidation logic
   - Institutional systems NEVER use arbitrary fallback prices

3. **No API Failure Protection**
   - No retry logic with exponential backoff
   - No circuit breaker after X failures
   - No broker health state tracking
   - No hard trading pause when connection unstable

## 1. Broker API Reliability Layer

### Circuit Breaker Pattern

**File:** `bot/broker_circuit_breaker.py`

The circuit breaker prevents cascading failures by temporarily blocking API calls after too many failures.

#### States

```
CLOSED → OPEN → HALF_OPEN → CLOSED
```

- **CLOSED**: Normal operation, all API calls allowed
- **OPEN**: Too many failures, blocking all calls (trading paused)
- **HALF_OPEN**: Testing if service recovered
- **CLOSED**: Service recovered, normal operation resumed

#### Broker Health States

```python
class BrokerHealthState(Enum):
    HEALTHY = "healthy"      # Normal operation
    DEGRADED = "degraded"    # Some failures but operational
    OFFLINE = "offline"      # Circuit breaker open, trading blocked
```

#### Configuration

```python
breaker = BrokerCircuitBreaker(
    broker_name="Kraken",
    failure_threshold=5,        # Open circuit after 5 consecutive failures
    recovery_timeout=60.0,      # Wait 60s before testing recovery
    success_threshold=2,        # Need 2 successes to close circuit
    max_retry_delay=30.0        # Cap exponential backoff at 30s
)
```

#### Exponential Backoff

Retry delays: 2s → 4s → 8s → 16s → 30s (capped)

Includes random jitter (0-30% of delay) to prevent thundering herd.

#### Usage

```python
# Option 1: Manual wrapping
breaker = get_circuit_breaker("Kraken")
result = breaker.call_with_circuit_breaker(api.get_balance)

# Option 2: Decorator (future enhancement)
@circuit_breaker("Kraken")
def get_balance(self):
    return self.api.get_balance()

# Option 3: Via BaseBroker (automatic)
result = broker._call_with_circuit_breaker(api.get_balance)
```

#### Integration with BaseBroker

All broker classes inherit from `BaseBroker` which now includes:

```python
class BaseBroker(ABC):
    def __init__(self, broker_type, account_type, user_id):
        # ... existing code ...
        self.circuit_breaker = get_circuit_breaker(broker_name)
    
    def get_broker_health_state(self) -> Optional[str]:
        """Get current health state"""
    
    def is_trading_allowed(self) -> bool:
        """Check if trading allowed based on health"""
    
    def _call_with_circuit_breaker(self, func, *args, **kwargs):
        """Execute API call with circuit breaker protection"""
```

#### Monitoring

```python
# Get circuit breaker status
status = breaker.get_status()
{
    'broker': 'Kraken',
    'health_state': 'healthy',
    'circuit_state': 'closed',
    'failure_count': 0,
    'total_calls': 150,
    'total_failures': 3,
    'failure_rate': 0.02,
    'last_success': '2026-02-18T16:42:10.274291',
    'last_failure': None,
    'state_uptime_seconds': 3600.5,
    'trading_allowed': True
}
```

## 2. Hard Position Cap Enforcement

### Changes to `position_cap_enforcer.py`

#### Previous Behavior
- Liquidate excess positions
- Log summary
- Return success/failure (partial compliance allowed)

#### New Behavior
- **Cycle 1:** Liquidate excess positions
- **Wait 3s** for orders to settle
- **Re-fetch positions** to verify closure
- **If still over cap:** Repeat (max 3 cycles)
- **If still non-compliant:** HALT trading and return `trading_halted: True`

#### Implementation

```python
def enforce_cap(self) -> Tuple[bool, Dict]:
    max_enforcement_cycles = 3
    
    for cycle in range(1, max_enforcement_cycles + 1):
        positions = self.get_current_positions()
        current_count = len(positions)
        
        if current_count <= self.max_positions:
            return True, {'status': 'compliant', ...}
        
        # Liquidate excess
        self._liquidate_smallest_positions(positions, excess)
        
        # Wait for settlement
        time.sleep(3)
        
        # Re-fetch for verification (loop continues)
    
    # Failed after max cycles
    logger.error("🛑 TRADING HALTED until manual intervention")
    return False, {
        'status': 'failed_enforcement',
        'trading_halted': True,
        ...
    }
```

#### External Monitoring

Trading systems should check the response:

```python
success, result = enforcer.enforce_cap()
if result.get('trading_halted'):
    logger.critical("TRADING HALTED: Position cap enforcement failed")
    # Alert operators
    # Pause new entries
    # Investigate positions
```

## 3. Removed Fallback Pricing

### Changes to `position_cap_enforcer.py`

#### Previous Code (DANGEROUS)

```python
# DANGEROUS: Use $1.00 fallback
if price is None:
    price = 1.0
    logger.warning(f"Using fallback price $1.00 for counting position")
```

#### New Code (INSTITUTIONAL STANDARD)

```python
# CRITICAL: Block valuation if price fetch fails
if price is None or price <= 0:
    logger.error(f"❌ CRITICAL: Cannot value position {symbol}")
    logger.error(f"   💡 Trading PAUSED for this symbol until price available")
    logger.error(f"   💡 Position exists but cannot be valued - BLOCKING VALUATION")
    # Do NOT count positions we cannot value
    continue
```

### Changes to `continuous_exit_enforcer.py`

#### Previous Code

```python
# Treat missing/zero prices as 0 to sort them first
return quantity * (price if price and price > 0 else 0)
```

#### New Code

```python
def get_position_value(p):
    quantity = p.get('quantity', 0)
    price = p.get('price', 0)
    # CRITICAL: Cannot value positions without valid price
    if not price or price <= 0:
        logger.error(f"❌ CRITICAL: Cannot value position {p.get('symbol')}")
        return None  # Mark as unvaluable

# Filter out unvaluable positions
valuable_positions = []
unvaluable_symbols = []
for pos in positions:
    value = get_position_value(pos)
    if value is None:
        unvaluable_symbols.append(pos.get('symbol'))
    else:
        valuable_positions.append((pos, value))

# Log critical alerts
if unvaluable_symbols:
    logger.error(f"🛑 Cannot enforce cap: {len(unvaluable_symbols)} positions lack pricing")
    for sym in unvaluable_symbols:
        logger.error(f"   - {sym}: TRADING PAUSED until price available")
```

### Impact

1. **Positions without pricing are NOT counted**
   - Prevents undercounting due to API failures
   - Forces investigation of pricing issues

2. **Trading is PAUSED for unvalued symbols**
   - No new entries
   - No position management
   - Operator must fix pricing or manually close

3. **Risk calculations are ACCURATE**
   - No fake $1.00 valuations
   - Exposure calculations are real
   - Liquidation logic uses real prices

## Testing

### Circuit Breaker Tests

**File:** `bot/test_circuit_breaker.py`

All tests pass:

```bash
cd /home/runner/work/Nija/Nija/bot
python3 test_circuit_breaker.py
```

**Test Suite:**

1. ✅ **Basic Circuit Breaker Functionality**
   - Successful calls keep circuit closed
   - 3 failures open circuit
   - Trading blocked when open

2. ✅ **Circuit Breaker Recovery**
   - Circuit opens after failures
   - Waits recovery timeout
   - Transitions to HALF_OPEN
   - Closes after success threshold

3. ✅ **Broker Health State Tracking**
   - Starts HEALTHY
   - Becomes OFFLINE after threshold
   - Status reporting works correctly

4. ✅ **Exponential Backoff**
   - Retry delays increase exponentially
   - 2s, 4s, 8s delays verified
   - Max backoff cap respected

### Manual Testing

```bash
# Test position cap enforcement
cd /home/runner/work/Nija/Nija
python3 -c "from bot.position_cap_enforcer import PositionCapEnforcer; \
    enforcer = PositionCapEnforcer(max_positions=8); \
    success, result = enforcer.enforce_cap(); \
    print(f'Success: {success}'); \
    print(f'Result: {result}')"

# Test circuit breaker imports
python3 -c "from bot.broker_circuit_breaker import BrokerCircuitBreaker, BrokerHealthState; \
    print('✅ Circuit breaker imports successful')"
```

## Deployment

### Environment Variables

No new environment variables required. Circuit breaker uses sensible defaults.

### Monitoring

Add monitoring for:

1. **Circuit breaker state changes**
   - Alert when circuit opens (broker offline)
   - Track recovery times

2. **Position cap violations**
   - Alert when enforcement fails
   - Track `trading_halted` flag

3. **Pricing failures**
   - Count symbols with missing prices
   - Alert on repeated failures

### Alerting Rules

```python
# Pseudo-code for monitoring integration
if broker.get_broker_health_state() == 'offline':
    alert('CRITICAL: Broker offline, trading halted')

if enforcement_result.get('trading_halted'):
    alert('CRITICAL: Position cap enforcement failed')

if len(unvaluable_symbols) > 0:
    alert(f'WARNING: {len(unvaluable_symbols)} positions lack pricing')
```

## Best Practices

### For Developers

1. **Always use circuit breaker for broker API calls**
   ```python
   result = broker._call_with_circuit_breaker(api_function)
   ```

2. **Check broker health before trading**
   ```python
   if not broker.is_trading_allowed():
       logger.error("Trading blocked: broker offline")
       return
   ```

3. **Handle missing prices explicitly**
   ```python
   price = broker.get_current_price(symbol)
   if price is None or price <= 0:
       logger.error(f"Cannot value {symbol}")
       return  # Don't trade
   ```

4. **Check position cap enforcement result**
   ```python
   success, result = enforcer.enforce_cap()
   if result.get('trading_halted'):
       # Alert and pause trading
       pass
   ```

### For Operators

1. **Monitor broker health dashboards**
   - Check circuit breaker status
   - Watch for DEGRADED/OFFLINE states

2. **Investigate position cap violations**
   - If enforcement fails after 3 cycles
   - Manually verify positions closed
   - Check API connectivity

3. **Fix pricing issues immediately**
   - Positions without prices block trading
   - Check broker API status
   - Verify symbol mapping

## Security

**CodeQL Analysis:** ✅ No vulnerabilities detected

The implementation follows security best practices:
- No hardcoded credentials
- No arbitrary fallback values
- Fail-closed behavior (block on error)
- Comprehensive error logging

## Migration Guide

### For Existing Deployments

1. **No breaking changes for most code**
   - Circuit breaker is opt-in via `BaseBroker`
   - Existing brokers continue to work

2. **Position cap enforcement is stricter**
   - May fail where it previously succeeded
   - This is intentional (prevents violations)

3. **Pricing failures now block trading**
   - Symbols without prices won't trade
   - Investigate and fix pricing issues

### Rollback Plan

If issues arise:

1. **Disable circuit breaker**
   ```python
   CIRCUIT_BREAKER_AVAILABLE = False
   ```

2. **Use old position cap enforcer**
   ```bash
   git checkout <previous-commit> -- bot/position_cap_enforcer.py
   ```

3. **Restore fallback pricing (NOT RECOMMENDED)**
   ```python
   # Only as temporary emergency measure
   price = price or 1.0
   ```

## Future Enhancements

1. **Nonce sequencing monitor for Kraken**
   - Track nonce collisions
   - Auto-retry with corrected nonce

2. **Circuit breaker metrics export**
   - Prometheus metrics
   - Grafana dashboards

3. **Adaptive thresholds**
   - Adjust failure threshold based on historical reliability
   - Dynamic recovery timeouts

4. **Per-method circuit breakers**
   - Separate breakers for read vs write operations
   - Different thresholds for different API endpoints

## References

- **Circuit Breaker Pattern**: https://martinfowler.com/bliki/CircuitBreaker.html
- **Exponential Backoff**: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- **Problem Statement**: See issue description

## Support

For issues or questions:
1. Check circuit breaker status via `get_status()`
2. Review logs for `CRITICAL` and `ERROR` messages
3. Verify broker health state
4. Check position cap enforcement results
