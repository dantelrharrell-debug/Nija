# Kraken Order Execution - Quick Reference

## 🔒 Kill Switches (Never Skip These!)

### 1. Check for Rejected Orders
```python
# ❌ BAD - Missing rejection check
result = kraken_api_call('AddOrder', params)
order_id = result['result']['txid'][0]  # DANGER: Could be None!

# ✅ GOOD - Check for rejection first
result = kraken_api_call('AddOrder', params)
if result and 'error' in result and result['error']:
    raise OrderRejectedError(f"Order rejected: {result['error']}")
```

### 2. Require txid Before Recording
```python
# ❌ BAD - Recording without txid
result = kraken_api_call('AddOrder', params)
trade_ledger.record_position(symbol, side, size)  # DANGER: Order might not exist!

# ✅ GOOD - Verify txid first
result = kraken_api_call('AddOrder', params)
order_id = result['result']['txid'][0] if result.get('result', {}).get('txid') else None
if not order_id:
    raise InvalidTxidError("No txid - order did not execute")
trade_ledger.record_position(symbol, side, size, txid=order_id)
```

### 3. Kill Zero-Price Fills
```python
# ❌ BAD - Recording without price validation
filled_price = order_details.get('price', 0.0)
trade_ledger.record_fill(order_id, filled_price)  # DANGER: Price could be 0!

# ✅ GOOD - Validate price first
filled_price = float(order_details.get('price', 0.0))
if filled_price <= 0:
    raise InvalidFillPriceError(f"Invalid fill price: {filled_price}")
trade_ledger.record_fill(order_id, filled_price)
```

## 🚨 Common Mistakes to Avoid

### Mistake #1: Assuming Order Success
```python
# ❌ WRONG
result = place_order(symbol, side, size)
# Assuming it worked...
record_position(...)  # DANGER!

# ✅ CORRECT
result = place_order(symbol, side, size)
if result.get('status') == 'error':
    logger.error(f"Order failed: {result.get('error')}")
    return None  # Don't record anything
```

### Mistake #2: Not Checking txid
```python
# ❌ WRONG
txid = result.get('result', {}).get('txid', [None])[0]
# Using txid without checking...
query_order(txid)  # DANGER: txid could be None!

# ✅ CORRECT
txid = result.get('result', {}).get('txid', [])
order_id = txid[0] if txid else None
if not order_id:
    raise InvalidTxidError("No txid returned")
query_order(order_id)
```

### Mistake #3: Recording Before Validation
```python
# ❌ WRONG
result = place_order(...)
trade_ledger.record_buy(...)  # Recording immediately
# Then checking later...
if result.get('status') == 'error':
    trade_ledger.delete_trade(...)  # Trying to undo

# ✅ CORRECT
result = place_order(...)
# Validate FIRST
if result.get('status') == 'error':
    return None
if not result.get('order_id'):
    raise InvalidTxidError()
# THEN record
trade_ledger.record_buy(...)
```

## 📋 Execution Checklist

Before recording ANY trade:
- [ ] Check if order was rejected (`result['error']`)
- [ ] Verify txid exists (`result['result']['txid'][0]`)
- [ ] Validate fill price > 0 (for market orders)
- [ ] Validate limit price > 0 (for limit orders, BEFORE API call)
- [ ] Log all validation failures with context

## 🔍 How to Verify a Trade is Real

A trade is only real if ALL of these are true:
1. ✅ No API errors in response
2. ✅ Valid txid in response
3. ✅ Fill price > 0
4. ✅ Order status = 'closed' (for market orders)
5. ✅ Filled volume > 0

## 📊 Monitoring

Watch for these in logs:
- `❌ KRAKEN ORDER REJECTED` - Order was rejected by API
- `❌ NO TXID` - Order didn't execute
- `❌ INVALID FILL PRICE` - Data corruption or API error

High rates (>5%) indicate a problem with:
- Insufficient funds
- Invalid symbols
- API connectivity
- Data quality issues

## 🛠️ Integration Points

| File | Function | Safety Checks |
|------|----------|---------------|
| `broker_integration.py` | `place_market_order()` | #2, #3, #4 |
| `broker_integration.py` | `place_limit_order()` | #2, #3, #4 (pre-validate) |
| `broker_manager.py` | `place_order()` | #2, #3 |
| `execution_engine.py` | `execute_entry()` | #2, #3, #4 |

## ⚡ Emergency Procedures

If fake trades are being recorded:
1. **STOP** - Pause trading immediately
2. **CHECK** - Review logs for safety check failures
3. **VERIFY** - Compare trades with Kraken UI
4. **FIX** - Identify which safety check is being bypassed
5. **TEST** - Validate fix with small test trades

## 📚 Further Reading

- Full execution flow: `KRAKEN_EXECUTION_FLOW.md`
- Exception classes: `bot/exceptions.py`
- Kraken validator: `bot/kraken_order_validator.py`
