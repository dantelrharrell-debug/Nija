# Copy Trading: Profit-Taking Synchronization

## Overview

This document details how NIJA's copy trading system ensures **all users take profit when the master takes profit**.

## Core Principle

**Every master trade is copied to users - both entries (BUY) and exits (SELL).**

When the master account executes ANY order, a trade signal is emitted and copied to all user accounts with proportional position sizing.

## Signal Emission Architecture

### Entry Orders (BUY)
```
Master executes BUY → emit_trade_signal(side="buy") → Copy Engine → Users execute BUY
```

### Exit Orders (SELL - Profit-Taking)
```
Master executes SELL → emit_trade_signal(side="sell") → Copy Engine → Users execute SELL
```

**Both flows are identical** - the system treats BUY and SELL signals the same way.

## Code Implementation

### Signal Emission (Both BUY and SELL)

**Location:** `bot/broker_manager.py` lines 3321-3363 (Coinbase) and 6655-6740 (Kraken)

```python
# COPY TRADING: Emit trade signal for master account trades
if self.account_type == AccountType.MASTER:
    from trade_signal_emitter import emit_trade_signal

    signal_emitted = emit_trade_signal(
        broker=broker_name,
        symbol=symbol,
        side=side,  # ← "buy" OR "sell" - both emit signals
        price=exec_price,
        size=quantity,
        size_type=size_type,
        order_id=order_id,
        master_balance=master_balance
    )
```

**Key Point:** The `side` parameter is passed as-is, meaning:
- BUY orders → `side="buy"` → Signal emitted
- SELL orders → `side="sell"` → Signal emitted ✅

### Signal Processing

**Location:** `bot/copy_trade_engine.py` lines 220-330

The copy engine processes both BUY and SELL signals identically:

```python
def copy_trade_to_users(self, signal: TradeSignal):
    """
    Copy a master trade to all active user accounts.
    Works for both BUY and SELL orders.
    """
    for user_id, user_broker in user_brokers.items():
        # Calculate scaled position size
        user_size = master_size × (user_balance / master_balance)

        # Execute order with same side as master
        order_result = user_broker.execute_order(
            symbol=signal.symbol,
            side=signal.side,  # ← "buy" or "sell"
            quantity=user_size,
            size_type=signal.size_type
        )
```

**No special handling for SELL vs BUY** - the engine copies both identically.

## Profit-Taking Scenarios

### Scenario 1: Partial Profit-Taking

**Master Action:**
- Sells 50% of position at TP1 target
- Keeps 50% for higher targets

**User Response:**
- SELL signal emitted with half position size
- Users sell 50% of their proportional positions
- Users keep 50% for higher targets

**Example:**
```
Master: Sells 0.005 BTC (50% of 0.01 BTC position)
User (10% scale): Sells 0.0005 BTC (50% of 0.001 BTC position)
```

### Scenario 2: Full Position Exit

**Master Action:**
- Sells 100% of position at TP3 target
- Closes position completely

**User Response:**
- SELL signal emitted with full position size
- Users sell 100% of their proportional positions
- All positions closed simultaneously

**Example:**
```
Master: Sells 0.01 BTC (100% exit)
User (10% scale): Sells 0.001 BTC (100% exit)
```

### Scenario 3: Stop-Loss Exit

**Master Action:**
- Price hits stop-loss
- Position force-liquidated via `force_liquidate()` method
- Executes SELL order to limit loss

**User Response:**
- SELL signal emitted (force_liquidate calls place_market_order)
- Users execute matching SELL orders
- All accounts exit to prevent further losses

**Example:**
```
Master: Hits stop-loss, sells 0.01 BTC at $45,000 (5% loss)
User (10% scale): Sells 0.001 BTC at $45,000 (same 5% loss)
```

### Scenario 4: Trailing Stop Activation

**Master Action:**
- Trailing stop activates after price retracement
- Executes SELL to lock in profits

**User Response:**
- SELL signal emitted
- Users execute at same trailing stop price
- Profits locked in for all accounts

## Signal Validation

### Only FILLED Orders Emit Signals

**Location:** `bot/trade_signal_emitter.py` lines 220-226

```python
def emit_trade_signal(..., order_status: str = "FILLED"):
    # Only emit signals for confirmed fills
    if order_status not in ["FILLED", "PARTIALLY_FILLED"]:
        logger.warning("⚠️ Signal NOT emitted - order must be FILLED")
        return False
```

**Protection:** Prevents copying of:
- Pending orders (not yet executed)
- "Signal approved" states (no actual trade)
- Cancelled orders
- Failed orders

**Applies to both BUY and SELL** - only filled trades emit signals.

## Position Sizing for Exits

Users exit with the **same proportion** as entries:

```
Entry:
  Master: $1,000 balance, buys $100 BTC (10% allocation)
  User:   $100 balance, buys $10 BTC (10% allocation)

Exit (Profit-Taking):
  Master: Sells $100 BTC position
  User:   Sells $10 BTC position (proportional)

Result:
  Both master and user exit 10% of their balance
  Profit % is identical for both accounts
```

## All Exit Methods Emit Signals

### 1. Standard Market Sell
```python
broker.place_market_order(symbol, 'sell', quantity)
```
✅ Emits signal (line 3342)

### 2. Close Position
```python
broker.close_position(symbol, quantity)
```
✅ Emits signal (calls place_market_order internally)

### 3. Force Liquidate
```python
broker.force_liquidate(symbol, quantity, reason="Stop loss")
```
✅ Emits signal (calls place_market_order with emergency flags)

### 4. Trailing Stop Exit
```python
trailing_system.check_trailing_take_profit(...)
→ broker.close_position(...)
```
✅ Emits signal (close_position → place_market_order)

### 5. Time-Based Exit
```python
strategy.check_position_age(...)
→ broker.place_market_order(symbol, 'sell', quantity)
```
✅ Emits signal (direct call to place_market_order)

**All exit paths** route through `place_market_order()`, which emits signals for master accounts.

## Monitoring Profit-Taking

### Log Messages for SELL Signals

**Master Side:**
```
📡 MASTER TRADE SIGNAL SENT (NOT EXECUTED)
   Master Account: Signal generated for copy trading
   Broker: coinbase
   Symbol: BTC-USD
   Side: SELL
   Size: 0.01 (base)
   Price: $55000.00
   ℹ️  This signal will be sent to user accounts for execution
```

**User Side:**
```
🔔 RECEIVED MASTER TRADE SIGNAL
   Symbol: BTC-USD
   Side: SELL
   Size: 0.01 (base)

🔄 Copying to user: user_001
   📤 Placing SELL order...
   🟢 COPY TRADE SUCCESS
      Side: SELL
      Size: 0.001 (base)
      ✅ Trade executed in your COINBASE account
```

## Verification Tests

See `bot/test_copy_trading_profit_taking.py` for comprehensive tests:

- ✅ SELL orders emit signals
- ✅ Copy engine processes SELL signals
- ✅ Users execute matching SELL orders
- ✅ BUY and SELL treated identically
- ✅ Partial exits are copied
- ✅ Full exits are copied
- ✅ Stop-loss exits are copied

Run tests:
```bash
python bot/test_copy_trading_profit_taking.py
```

## Troubleshooting

### Users Not Taking Profit

**Problem:** Master exits but users don't sell

**Diagnosis:**
1. Check if SELL signal was emitted:
   ```bash
   grep "SELL" nija.log | grep "SIGNAL SENT"
   ```

2. Check if copy engine is running:
   ```bash
   grep "COPY TRADE ENGINE STARTED" nija.log
   ```

3. Check for copy execution errors:
   ```bash
   grep "COPY TRADE.*SELL" nija.log
   ```

**Common Causes:**
- Master account type not set to MASTER
- Copy engine not started
- User broker disconnected
- Insufficient user balance for sell order
- Order status not FILLED (pending/cancelled)

### Partial Copy Execution

**Problem:** Some users take profit, others don't

**Diagnosis:**
```bash
grep "COPY TRADE RESULTS" nija.log -A 5
```

**Common Causes:**
- Individual user broker disconnection
- Insufficient position size (dust threshold)
- User-specific API errors
- Symbol not supported on user's exchange

## Best Practices

### For Small Accounts
- Ensure positions are large enough to exit (> $1.00 dust threshold)
- Monitor first few exits to verify synchronization
- Check user broker connectivity before master trades

### For All Users
- Enable copy trading mode: `COPY_TRADING_MODE=MASTER_FOLLOW`
- Verify copy engine starts on bot launch
- Monitor logs for signal emission confirmation
- Test with small positions first

## Summary

✅ **Profit-taking IS synchronized** between master and users
✅ **SELL orders emit signals** just like BUY orders
✅ **Copy engine processes SELL** identically to BUY
✅ **All exit methods** (stop-loss, trailing, time-based) emit signals
✅ **Position sizing** maintains proportional exits
✅ **Tested and verified** in production code

**Users will automatically take profit when the master takes profit.**

## Related Documentation

- `COPY_TRADING_SETUP.md` - General copy trading setup
- `bot/trade_signal_emitter.py` - Signal emission code
- `bot/copy_trade_engine.py` - Signal processing code
- `bot/broker_manager.py` - Order execution with signal emission
