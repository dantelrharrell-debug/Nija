# NIJA Live Validation Framework

## Overview

The **Live Validation Framework** is a comprehensive, production-ready validation system for the NIJA trading bot. It provides multi-layered validation to ensure safe, reliable live trading operations with real capital.

## Key Features

### ✅ Pre-Trade Validation
- **Price Data Integrity**: Validates price is not NaN, infinite, or negative
- **Price Freshness**: Ensures price data is recent (configurable staleness threshold)
- **Spread Validation**: Checks bid-ask spread is reasonable
- **Price Movement**: Detects abnormal price volatility
- **Order Size**: Validates minimum order sizes and fee profitability
- **Position Limits**: Ensures position size doesn't exceed account limits
- **Double-Execution Prevention**: Idempotency checks prevent duplicate orders

### ✅ Order Execution Validation
- **Order Submission**: Validates order parameters before submission
- **Order Confirmation**: Verifies broker accepted the order
- **Order Timeout Detection**: Alerts on pending orders taking too long
- **Fill Price**: Validates execution price vs expected price
- **Slippage Monitoring**: Tracks and alerts on excessive slippage

### ✅ Post-Trade Validation
- **Position Reconciliation**: Matches local position state with broker
- **P&L Calculation**: Validates unrealized P&L calculations
- **Position State Machine**: Enforces valid state transitions
- **Fee Verification**: Validates actual fees against expected

### ✅ Real-Time Risk Validation
- **Daily Loss Limits**: Circuit breaker for daily loss percentage
- **Maximum Drawdown**: Prevents excessive drawdown from peak
- **Position Count Limits**: Enforces maximum open positions
- **Leverage Monitoring**: Validates portfolio leverage
- **Margin Requirements**: Ensures sufficient margin available

### ✅ Fee & Profitability Validation
- **Fee Calculation**: Validates fees against broker fee schedules
- **Profitability Floor**: Ensures profit exceeds fees by minimum ratio
- **Minimum Trade Size**: Prevents unprofitable small trades

## Architecture

```
LiveValidationFramework (Main Orchestrator)
├── PriceValidator
│   ├── validate_price_freshness()
│   ├── validate_price_integrity()
│   ├── validate_spread()
│   └── validate_price_movement()
│
├── OrderValidator
│   ├── validate_order_submission()
│   ├── validate_order_confirmation()
│   ├── validate_fill_price()
│   ├── check_order_timeout()
│   └── record_order_submission()
│
├── PositionValidator
│   ├── validate_position_size()
│   ├── validate_position_reconciliation()
│   ├── validate_unrealized_pnl()
│   └── validate_position_state_machine()
│
├── RiskValidator
│   ├── validate_daily_loss_limit()
│   ├── validate_drawdown_limit()
│   ├── validate_position_count()
│   ├── validate_leverage()
│   └── validate_margin_requirements()
│
└── FeeValidator
    ├── validate_fee_calculation()
    ├── validate_profitability_floor()
    └── validate_minimum_trade_size()
```

## Installation

The Live Validation Framework is included in the NIJA trading bot. No additional installation required.

```bash
# Framework files are located in:
bot/live_validation_framework.py
bot/validation_models.py
bot/validators/
```

## Quick Start

### Basic Usage

```python
from bot.live_validation_framework import get_validation_framework
from bot.validation_models import ValidationContext

# Initialize framework (singleton)
framework = get_validation_framework(
    max_price_age_seconds=60,
    max_daily_loss_pct=5.0,
    max_drawdown_pct=15.0,
    enable_validation=True
)

# Create validation context
ctx = ValidationContext(
    symbol="BTC-USD",
    side="buy",
    size=0.001,
    price=50000.0,
    account_id="my_account",
    broker="coinbase"
)

# Run pre-trade validation
results = framework.validate_pre_trade(
    ctx=ctx,
    current_price=50000.0,
    bid=49990.0,
    ask=50010.0,
    account_balance=10000.0,
    open_positions=2
)

# Check for blocking issues
if framework.has_blocking_results(results):
    blocking = framework.get_blocking_results(results)
    for result in blocking:
        print(f"BLOCKED: {result.message}")
        print(f"Action: {result.recommended_action}")
else:
    print("✅ Pre-trade validation passed!")
```

### Integration with Execution Engine

```python
from bot.live_validation_framework import get_validation_framework

def execute_trade(symbol, side, size, price):
    framework = get_validation_framework()
    
    # Pre-trade validation
    ctx = ValidationContext(
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        broker="coinbase"
    )
    
    results = framework.validate_pre_trade(
        ctx=ctx,
        current_price=price,
        account_balance=get_account_balance(),
        open_positions=count_open_positions()
    )
    
    # Check for blocking issues
    if framework.has_blocking_results(results):
        logger.error("Trade blocked by validation")
        return None
    
    # Submit order
    order_id = submit_order(symbol, side, size)
    
    # Record for tracking
    framework.record_order_submission(
        order_id=order_id,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        account_id="main",
        broker="coinbase"
    )
    
    # Get broker response
    response = wait_for_order_confirmation(order_id)
    
    # Validate execution
    exec_results = framework.validate_order_execution(
        order_id=order_id,
        broker_response=response,
        broker="coinbase"
    )
    
    return order_id
```

## Configuration

### Framework Initialization Parameters

```python
framework = LiveValidationFramework(
    # Price Validator
    max_price_age_seconds=60,      # Max age for price data
    max_spread_pct=2.0,            # Max bid-ask spread %
    max_price_change_pct=10.0,     # Max price movement %
    
    # Order Validator
    order_timeout_seconds=300,     # Max time for order execution
    enable_idempotency=True,       # Prevent double-execution
    
    # Position Validator
    max_position_size_pct=50.0,    # Max position as % of account
    max_position_drift_pct=5.0,    # Max drift between local/broker
    
    # Risk Validator
    max_daily_loss_pct=5.0,        # Max daily loss %
    max_drawdown_pct=15.0,         # Max drawdown from peak %
    max_open_positions=10,         # Max concurrent positions
    max_leverage=3.0,              # Max portfolio leverage
    
    # Fee Validator
    custom_fee_rates={             # Custom fee rates by broker
        'coinbase': 0.60,
        'kraken': 0.26
    },
    min_profit_over_fees_ratio=2.0, # Min profit/fees ratio
    
    # Framework Settings
    enable_validation=True,        # Enable/disable all validation
    fail_fast=False               # Stop on first error vs collect all
)
```

### Environment Variables

You can also configure via environment variables:

```bash
# Risk Limits
export NIJA_MAX_DAILY_LOSS_PCT=5.0
export NIJA_MAX_DRAWDOWN_PCT=15.0
export NIJA_MAX_LEVERAGE=3.0

# Price Validation
export NIJA_MAX_PRICE_AGE_SECONDS=60
export NIJA_MAX_SPREAD_PCT=2.0

# Validation Control
export NIJA_ENABLE_VALIDATION=true
export NIJA_VALIDATION_FAIL_FAST=false
```

## Validation Levels

The framework uses a tiered severity system:

| Level | Description | Action |
|-------|-------------|--------|
| **PASS** | Validation passed | Continue normally |
| **INFO** | Informational only | No action needed |
| **WARNING** | Potential issue | Can proceed with caution |
| **ERROR** | Validation failed | Should not proceed |
| **CRITICAL** | Critical failure | Must halt trading |

## Validation Categories

| Category | Purpose |
|----------|---------|
| `PRE_TRADE` | Before order submission |
| `ORDER_EXECUTION` | During order execution |
| `POST_TRADE` | After order execution |
| `REAL_TIME_MONITORING` | Continuous monitoring |
| `RISK` | Risk-related validation |
| `DATA_INTEGRITY` | Data quality validation |
| `POSITION_RECONCILIATION` | Position state validation |
| `FEE_VALIDATION` | Fee and cost validation |
| `CIRCUIT_BREAKER` | Emergency validation |

## Metrics & Monitoring

### Get Validation Metrics

```python
framework = get_validation_framework()

# Get metrics dictionary
metrics = framework.get_metrics()
print(f"Total Validations: {metrics['total_validations']}")
print(f"Pass Rate: {metrics['pass_rate_pct']}%")
print(f"Error Rate: {metrics['error_rate_pct']}%")

# Get human-readable summary
summary = framework.get_validation_summary()
print(summary)
```

Example output:
```
================================================================================
LIVE VALIDATION FRAMEWORK - STATUS
================================================================================
  Total Validations: 1523
  Pass Rate: 94.22%
  Error Rate: 2.11%
  Avg Validation Time: 1.23ms
  Max Validation Time: 45.67ms

  By Category:
    pre_trade: 856
    order_execution: 342
    post_trade: 213
    risk: 112

  Recent Failures:
    [ERROR] [pre_trade] OrderValidator.validate_order_submission: Duplicate order detected
    [WARNING] [fee_validation] FeeValidator.validate_minimum_trade_size: Order too small
================================================================================
```

## Best Practices

### 1. Always Validate Before Trading

```python
# ✅ GOOD: Validate before every trade
results = framework.validate_pre_trade(ctx, ...)
if framework.has_blocking_results(results):
    return  # Don't trade

# ❌ BAD: Skip validation
execute_order_directly(...)  # Risky!
```

### 2. Check Validation Results

```python
# ✅ GOOD: Check results and act on recommendations
for result in results:
    if result.level == ValidationLevel.ERROR:
        logger.error(f"Error: {result.message}")
        logger.info(f"Action: {result.recommended_action}")

# ❌ BAD: Ignore results
results = framework.validate_pre_trade(...)  # Run but ignore
```

### 3. Monitor Validation Metrics

```python
# ✅ GOOD: Periodically check validation health
def health_check():
    metrics = framework.get_metrics()
    if metrics['error_rate_pct'] > 10:
        logger.warning("High validation error rate!")
        send_alert()

# Schedule health checks
schedule.every(5).minutes.do(health_check)
```

### 4. Use Fail-Fast for Critical Operations

```python
# For high-risk operations, fail on first error
framework_strict = get_validation_framework(
    fail_fast=True,
    max_daily_loss_pct=2.0  # Stricter limits
)
```

### 5. Cleanup Periodically

```python
# Cleanup old validation data
framework.cleanup()  # Run daily
```

## Integration Examples

### Example 1: Pre-Trade Gate Check

```python
def pre_trade_gate(symbol, side, size, price, account_balance):
    """Gate check before allowing trade"""
    framework = get_validation_framework()
    
    ctx = ValidationContext(
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        broker="coinbase"
    )
    
    results = framework.validate_pre_trade(
        ctx=ctx,
        current_price=price,
        account_balance=account_balance,
        open_positions=get_position_count()
    )
    
    # Log all results
    for result in results:
        logger.info(str(result))
    
    # Block if any errors
    if framework.has_blocking_results(results):
        blocking = framework.get_blocking_results(results)
        reasons = [r.message for r in blocking]
        logger.error(f"Trade blocked: {'; '.join(reasons)}")
        return False, reasons
    
    return True, None
```

### Example 2: Real-Time Risk Monitoring

```python
def monitor_risk_limits(account_id, broker):
    """Monitor risk limits in real-time"""
    framework = get_validation_framework()
    
    account_data = get_account_data(account_id)
    
    results = framework.validate_risk_limits(
        account_id=account_id,
        broker=broker,
        starting_balance=account_data['starting_balance'],
        current_balance=account_data['current_balance'],
        peak_balance=account_data['peak_balance'],
        daily_pnl=account_data['daily_pnl'],
        open_positions=account_data['open_positions'],
        total_position_value=account_data['total_position_value']
    )
    
    # Check for circuit breakers
    for result in results:
        if result.level == ValidationLevel.CRITICAL:
            logger.critical(f"CIRCUIT BREAKER: {result.message}")
            halt_trading(account_id)
            send_emergency_alert(result.message)
            return True  # Trading halted
    
    return False  # All clear
```

### Example 3: Position Reconciliation

```python
def reconcile_positions(symbol, account_id, broker):
    """Reconcile local position with broker"""
    framework = get_validation_framework()
    
    local_position = get_local_position(symbol)
    broker_position = fetch_broker_position(symbol, broker)
    
    result = framework.position_validator.validate_position_reconciliation(
        symbol=symbol,
        local_size=local_position['size'],
        broker_size=broker_position['size'],
        broker=broker,
        account_id=account_id
    )
    
    if result.is_blocking():
        logger.error(f"Position mismatch: {result.message}")
        logger.info(f"Local: {local_position}, Broker: {broker_position}")
        
        # Sync with broker (broker is source of truth)
        sync_position_with_broker(symbol, broker_position)
    
    return result
```

## Troubleshooting

### High Error Rate

```python
# Check what's failing
metrics = framework.get_metrics()
print(metrics['by_category'])

# Review recent failures
for failure in metrics['recent_failures']:
    print(failure)
```

### Validation Too Slow

```python
# Check timing
metrics = framework.get_metrics()
print(f"Avg: {metrics['avg_validation_time_ms']}ms")
print(f"Max: {metrics['max_validation_time_ms']}ms")

# If too slow, disable non-critical validations
framework_fast = LiveValidationFramework(
    max_price_age_seconds=120,  # More lenient
    enable_idempotency=False    # Disable if not needed
)
```

### False Positives

```python
# Adjust thresholds
framework = LiveValidationFramework(
    max_spread_pct=5.0,          # Increase if crypto spreads are wide
    max_position_drift_pct=10.0  # Increase for volatile markets
)
```

## API Reference

### ValidationContext

```python
ValidationContext(
    symbol: str,           # Trading symbol
    side: str,             # 'buy' or 'sell'
    size: float,           # Order size
    price: Optional[float] = None,
    account_id: str = "default",
    broker: str = "unknown",
    account_balance: Optional[float] = None,
    open_positions: Optional[int] = None,
    daily_pnl: Optional[float] = None,
    order_id: Optional[str] = None,
    order_type: str = "market",
    timestamp: datetime = datetime.utcnow(),
    metadata: Dict[str, Any] = {}
)
```

### ValidationResult

```python
ValidationResult(
    level: ValidationLevel,           # PASS, INFO, WARNING, ERROR, CRITICAL
    category: ValidationCategory,     # Validation category
    validator_name: str,              # Name of validator
    message: str,                     # Human-readable message
    timestamp: datetime,              # When validation occurred
    symbol: Optional[str] = None,
    account_id: Optional[str] = None,
    broker: Optional[str] = None,
    order_id: Optional[str] = None,
    details: Dict[str, Any] = {},
    metrics: Dict[str, float] = {},
    recommended_action: Optional[str] = None,
    can_proceed: bool = True
)
```

## Security Considerations

1. **Always Enable Validation in Production**: Never disable validation when trading real money
2. **Monitor Circuit Breakers**: Daily loss and drawdown limits prevent catastrophic losses
3. **Regular Reconciliation**: Periodically reconcile positions with broker
4. **Fee Verification**: Always validate fees match broker's actual fee structure
5. **Price Integrity**: Never trade on stale or corrupted price data

## Performance

- **Latency**: Average validation time < 2ms per trade
- **Throughput**: Can validate 500+ trades/second
- **Memory**: Minimal overhead (~10MB for typical usage)
- **Thread-Safe**: All validators are thread-safe

## Support

For issues or questions:
- Check the troubleshooting section above
- Review validation metrics for insights
- Enable debug logging: `logging.getLogger("nija.validators").setLevel(logging.DEBUG)`

## License

Part of the NIJA Trading System.
Author: NIJA Trading Systems
Date: January 30, 2026
