# Kraken Order Execution Flow with Safety Checks

## Overview

This document describes the **fail-safe execution flow** for Kraken orders, ensuring that fake trades can never be recorded in the system.

## Critical Safety Checks (Kill Switches)

### 🛑 Safety Check #1: Broker Context Validation
**Status:** N/A - No cycle_broker concept found in codebase

This check would validate that the broker executing the order matches the expected broker for the trading cycle.

```python
# Example (if implemented in future):
if cycle_broker != execution_broker:
    raise BrokerMismatchError("Broker mismatch — aborting trade")
```

### 🛑 Safety Check #2: Hard-Stop on Rejected Orders
**Location:**
- `bot/broker_integration.py` (KrakenClient.place_market_order, line ~1098)
- `bot/broker_integration.py` (KrakenClient.place_limit_order, line ~1324)
- `bot/broker_manager.py` (KrakenBroker.place_order, line ~6218)
- `bot/execution_engine.py` (ExecutionEngine.execute_entry, line ~125)

**Implementation:**
```python
# Check if Kraken API returned an error
if result and 'error' in result and result['error']:
    error_msgs = ', '.join(result['error'])
    logger.error("❌ KRAKEN ORDER REJECTED - ABORTING")
    logger.error(f"   Rejection Reason: {error_msgs}")
    logger.error("   ⚠️  ORDER REJECTED - DO NOT RECORD TRADE")
    raise OrderRejectedError(f"Order rejected by Kraken: {error_msgs}")
```

**Purpose:** Prevents recording rejected orders as successful trades.

### 🛑 Safety Check #3: Require txid Before Recording Position
**Location:**
- `bot/broker_integration.py` (KrakenClient.place_market_order, line ~1109)
- `bot/broker_integration.py` (KrakenClient.place_limit_order, line ~1335)
- `bot/broker_manager.py` (KrakenBroker.place_order, line ~6227)
- `bot/execution_engine.py` (ExecutionEngine.execute_entry, line ~135)

**Implementation:**
```python
# Extract txid from Kraken response
order_result = result['result']
txid = order_result.get('txid', [])
order_id = txid[0] if txid else None

# CRITICAL: No txid → No trade executed → Raise exception
if not order_id:
    logger.error("❌ NO TXID - CANNOT RECORD POSITION")
    logger.error("   ⚠️  Order must have valid txid before recording position")
    raise InvalidTxidError("No txid returned from Kraken - order did not execute")
```

**Purpose:** Ensures that only trades with valid Kraken transaction IDs are recorded. Without a txid, the trade does not exist in Kraken's system.

### 🛑 Safety Check #4: Kill Zero-Price Fills Immediately
**Location:**
- `bot/broker_integration.py` (KrakenClient.place_market_order, line ~1164)
- `bot/broker_integration.py` (KrakenClient.place_limit_order, line ~1349)
- `bot/execution_engine.py` (ExecutionEngine.execute_entry, line ~168)

**Implementation:**
```python
# Validate fill price is greater than zero
if filled_price <= 0:
    logger.error("❌ INVALID FILL PRICE - ABORTING")
    logger.error(f"   Filled Price: {filled_price} (INVALID)")
    logger.error("   ⚠️  Price must be greater than zero")
    raise InvalidFillPriceError(f"Invalid fill price: {filled_price}")
```

**Purpose:** Prevents recording trades with invalid (zero or negative) fill prices, which indicate data corruption or API errors.

## Execution Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Strategy Generates Trade Signal                             │
│    - Symbol, Side, Quantity determined                         │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Pre-Order Validation                                        │
│    - Symbol format validation (BTC → XBT)                      │
│    - Minimum order size checks (Kraken minimums)               │
│    - Fee-adjusted size calculation                             │
│    - Balance checks (EXIT_ONLY mode if low balance)            │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Build AddOrder Parameters                                   │
│    order_params = {                                            │
│        'pair': kraken_symbol,  # e.g., 'XXBTZUSD'              │
│        'type': 'buy' or 'sell',                                │
│        'ordertype': 'market' or 'limit',                       │
│        'volume': str(size),                                    │
│        'price': str(price)  # limit orders only                │
│    }                                                           │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Execute Kraken API Call                                     │
│    result = _kraken_api_call('AddOrder', order_params)         │
│    - Global nonce management                                   │
│    - Thread-safe serialized execution                          │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 🛑 SAFETY CHECK #2: Order Rejection Check                      │
│                                                                 │
│    if result['error']:                                         │
│        ❌ ABORT - Order rejected by Kraken                     │
│        ❌ DO NOT RECORD TRADE                                  │
│        raise OrderRejectedError()                              │
└─────────────────────┬───────────────────────────────────────────┘
                      │ ✅ No errors
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 🛑 SAFETY CHECK #3: txid Validation                            │
│                                                                 │
│    order_id = result['result']['txid'][0]                      │
│    if not order_id:                                            │
│        ❌ ABORT - No txid means no trade executed              │
│        ❌ DO NOT RECORD TRADE                                  │
│        raise InvalidTxidError()                                │
└─────────────────────┬───────────────────────────────────────────┘
                      │ ✅ Valid txid received
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Query Order Details (for market orders)                     │
│    order_query = _kraken_api_call('QueryOrders', {'txid': id}) │
│    - Extract filled_price from order details                   │
│    - Extract filled_volume                                     │
│    - Verify order status = 'closed'                            │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 🛑 SAFETY CHECK #4: Fill Price Validation                      │
│                                                                 │
│    if filled_price <= 0:                                       │
│        ❌ ABORT - Invalid fill price                           │
│        ❌ DO NOT RECORD TRADE                                  │
│        raise InvalidFillPriceError()                           │
└─────────────────────┬───────────────────────────────────────────┘
                      │ ✅ Valid fill price
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Record Trade in System                                      │
│    ✅ SAFE TO RECORD - All checks passed                       │
│    - Record in trade_ledger database                           │
│    - Open position in position_manager                         │
│    - Log trade confirmation with txid                          │
│    - Emit trade signal (for copy trading)                      │
└─────────────────────────────────────────────────────────────────┘
```

## Exception Handling

All safety checks use custom exceptions defined in `bot/exceptions.py`:

| Exception | Raised When | Handler Behavior |
|-----------|-------------|------------------|
| `OrderRejectedError` | Kraken API returns errors | Do not record trade, return error status |
| `InvalidTxidError` | No txid in Kraken response | Do not record trade, raise exception |
| `InvalidFillPriceError` | Fill price ≤ 0 | Do not record trade, raise exception |
| `BrokerMismatchError` | Broker context mismatch | Do not execute trade, raise exception |

## Integration Points

### 1. broker_integration.py (KrakenClient)
- **Methods:** `place_market_order()`, `place_limit_order()`
- **Checks:** #2, #3, #4
- **Behavior:** Raises exceptions on safety check failure

### 2. broker_manager.py (KrakenBroker)
- **Methods:** `place_order()`
- **Checks:** #2, #3
- **Behavior:** Returns `{"status": "error"}` on safety check failure

### 3. execution_engine.py (ExecutionEngine)
- **Methods:** `execute_entry()`
- **Checks:** #2, #3, #4
- **Behavior:** Returns `None` on safety check failure (prevents position recording)

## Developer Guidelines

### ✅ DO:
1. **Always check for txid** before recording any trade
2. **Always validate fill prices** are greater than zero
3. **Always handle OrderRejectedError** gracefully
4. **Always log safety check failures** with detailed context
5. **Always use the validated order_id** when recording positions

### ❌ DON'T:
1. **Never record a trade** without a valid txid
2. **Never ignore API error responses** from Kraken
3. **Never assume an order executed** without verification
4. **Never record positions** with zero or negative prices
5. **Never bypass safety checks** for "testing" or "debugging"

## Testing

To test the safety checks:

1. **Test Rejected Orders:**
   ```python
   # Mock a rejected order response
   result = {
       'error': ['EOrder:Insufficient funds']
   }
   # Should raise OrderRejectedError
   ```

2. **Test Missing txid:**
   ```python
   # Mock a response without txid
   result = {
       'result': {}  # No txid field
   }
   # Should raise InvalidTxidError
   ```

3. **Test Zero-Price Fill:**
   ```python
   # Mock order details with zero price
   order_details = {
       'price': 0.0,
       'status': 'closed'
   }
   # Should raise InvalidFillPriceError
   ```

## Monitoring

Key metrics to monitor:

- **Rejected order count:** Track `OrderRejectedError` exceptions
- **Missing txid count:** Track `InvalidTxidError` exceptions
- **Invalid price count:** Track `InvalidFillPriceError` exceptions
- **Safety check pass rate:** Should be > 95% under normal conditions

## Troubleshooting

### Issue: Trade not recorded despite successful order
**Diagnosis:** Check logs for safety check failures
**Solution:** Verify all safety checks pass, especially txid validation

### Issue: OrderRejectedError on valid orders
**Diagnosis:** Check Kraken API error message in logs
**Solution:** Fix underlying issue (insufficient funds, invalid symbol, etc.)

### Issue: InvalidFillPriceError after order execution
**Diagnosis:** Kraken API may be returning incomplete data
**Solution:** Increase order query delay (currently 0.5s), check API status

## Future Enhancements

1. **Broker Context Validation (Check #1):**
   - Implement cycle_broker tracking
   - Validate execution_broker matches expected broker

2. **Retry Logic:**
   - Add intelligent retry for transient API failures
   - Exponential backoff for rate limit errors

3. **Enhanced Monitoring:**
   - Dashboard for safety check metrics
   - Alerts for unusual failure rates

## References

- Kraken API Documentation: https://docs.kraken.com/rest/#tag/Trading/operation/addOrder
- NIJA Order Validator: `bot/kraken_order_validator.py`
- NIJA Exceptions: `bot/exceptions.py`
