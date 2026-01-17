# NIJA Copy Trading Guide

## Overview

NIJA now supports **automatic copy-trading** where master account trades are instantly replicated to user accounts with proportional position sizing based on account equity.

## How Copy Trading Works

```
MASTER ACCOUNT                           USER ACCOUNTS
     ↓                                        ↓
Places Trade                        Automatically Replicates
(e.g., $500 BTC)                    (scaled to user balance)
     ↓                                        ↓
Signal Emitted                      Copy Engine Processes
     ↓                                        ↓
Trade Confirmed                     User Trades Execute
(order_id captured)                 (proportional sizing)
```

## Architecture

### 1. **Trade Signal Emitter** (`bot/trade_signal_emitter.py`)

When the master account places a trade, a signal is emitted containing:
- **Broker**: Exchange name (coinbase, kraken, etc.)
- **Symbol**: Trading pair (BTC-USD, ETH-USD, etc.)
- **Side**: buy or sell
- **Price**: Execution price
- **Size**: Position size
- **Size Type**: "quote" (USD amount) or "base" (crypto amount)
- **Order ID**: Master account order ID
- **Master Balance**: Master account balance (for position sizing)
- **Timestamp**: When trade was executed

### 2. **Copy Trade Engine** (`bot/copy_trade_engine.py`)

Runs in a background thread and:
- Listens for trade signals from master account
- Iterates through all active user accounts
- Calculates appropriate position size for each user
- Places the same order on each user's exchange
- Logs success/failure per user (isolation)
- **Never blocks**: If one user fails, others continue

### 3. **Position Sizer** (`bot/position_sizer.py`)

Calculates user position sizes using **equity-based scaling**:

```
user_size = master_size × (user_balance / master_balance)
```

**Example:**
- Master: $10,000 balance → places $500 BTC trade
- User A: $1,000 balance → receives $50 BTC trade (10% of master)
- User B: $5,000 balance → receives $250 BTC trade (50% of master)

**Benefits:**
- Users trade proportionally to their account size
- Risk management scales with capital
- Same risk/reward ratio as master account

### 4. **Broker Isolation**

Each user has their own:
- API client instance (no shared connections)
- Nonce management (prevents collisions)
- Rate limiting (independent quotas)
- Error handling (failures are isolated)

**Result**: One user's error never affects another user's trades.

## Signal Flow

### Master Places Order
```python
# In broker_manager.py (CoinbaseBroker.place_market_order)
# After order is confirmed successful:

from trade_signal_emitter import emit_trade_signal

emit_trade_signal(
    broker="coinbase",
    symbol="BTC-USD",
    side="buy",
    price=45000.0,
    size=500.0,
    size_type="quote",
    order_id="abc-123",
    master_balance=10000.0
)
```

### Copy Engine Processes
```python
# Background thread in copy_trade_engine.py
# Automatically consumes signals and replicates trades

for user_id, user_broker in active_users:
    # Calculate scaled size
    user_size = master_size * (user_balance / master_balance)
    
    # Place order on user's exchange
    result = user_broker.execute_order(
        symbol="BTC-USD",
        side="buy",
        quantity=user_size,
        size_type="quote"
    )
    
    # Log result (doesn't fail if one user fails)
    if result.success:
        log(f"✅ User {user_id}: Order {order_id}")
    else:
        log(f"❌ User {user_id}: {error}")
```

## Adding a New User Account

### Step 1: Set Environment Variables

For each user, set their exchange credentials:

**Kraken Example:**
```bash
# User: daivon_frazier
export KRAKEN_USER_DAIVON_API_KEY="your-api-key"
export KRAKEN_USER_DAIVON_API_SECRET="your-api-secret"

# User: tania_gilbert  
export KRAKEN_USER_TANIA_API_KEY="your-api-key"
export KRAKEN_USER_TANIA_API_SECRET="your-api-secret"
```

**Alpaca Example:**
```bash
# User: tania_gilbert
export ALPACA_USER_TANIA_API_KEY="your-api-key"
export ALPACA_USER_TANIA_API_SECRET="your-api-secret"
export ALPACA_USER_TANIA_PAPER="true"  # or "false" for live
```

### Step 2: User Connection Happens Automatically

The `multi_account_broker_manager.py` automatically:
1. Detects user credentials from environment variables
2. Creates separate broker instances for each user
3. Connects users to their exchanges
4. Registers users in the copy trade system

**No code changes needed** - just set environment variables!

### Step 3: Verify User Connection

Check logs for:
```
✅ USER:tania_gilbert KRAKEN connected
✅ Copy trade engine started - user trades will be replicated
```

## Position Sizing Examples

### Example 1: Small User Account
```
Master: $10,000 balance → $500 BTC buy
User:   $1,000 balance → $50 BTC buy (10x smaller)

Scale Factor: 1000 / 10000 = 0.10 (10%)
User Size: $500 × 0.10 = $50
```

### Example 2: Large User Account
```
Master: $10,000 balance → $500 BTC buy  
User:   $50,000 balance → $2,500 BTC buy (5x larger)

Scale Factor: 50000 / 10000 = 5.0 (500%)
User Size: $500 × 5.0 = $2,500
```

### Example 3: Minimum Size Protection
```
Master: $10,000 balance → $20 BTC buy
User:   $100 balance → Position too small (would be $0.20)

Result: User trade SKIPPED (below $1 minimum)
Reason: "Position too small: $0.20 < $1.00 minimum"
```

## Monitoring Copy Trades

### Successful Copy Trade Logs
```
🔔 RECEIVED MASTER TRADE SIGNAL
   Symbol: BTC-USD
   Side: BUY
   Size: 500.0 (quote)
   Broker: coinbase

🔄 Copying to user: tania_gilbert
   User Balance: $1,000.00
   Master Balance: $10,000.00
   Calculated Size: 50.0 (quote)
   Scale Factor: 0.1000 (10.00%)
   📤 Placing BUY order...
   
🟢 COPY TRADE SUCCESS
   User: tania_gilbert
   Order ID: xyz-789
   Symbol: BTC-USD
   Side: BUY
   Size: 50.0 (quote)

📊 COPY TRADE RESULTS
   Total Users: 2
   Successful: 2
   Failed: 0
```

### Failed Copy Trade Logs
```
🔄 Copying to user: daivon_frazier
   ⚠️  Position sizing failed: Position too small: $0.50 < $1.00 minimum

❌ COPY TRADE FAILED
   User: daivon_frazier
   Error: Position too small
```

## Trade Visibility

All user trades appear in their exchange dashboards:

### Coinbase
- Go to: https://www.coinbase.com/advanced-trade
- View: Orders → Filled Orders
- See: Your copy-traded orders with timestamps

### Kraken  
- Go to: https://pro.kraken.com
- View: History → Trades
- See: Your copy-traded orders with order IDs

## Error Handling

### User-Specific Errors
If one user fails, others continue:
```
✅ User A: Trade successful
❌ User B: Insufficient balance - SKIPPED
✅ User C: Trade successful
```

### Master Trade Failures
If master trade fails, NO user trades execute:
```
❌ Master trade failed - no signal emitted
→ Users receive nothing (correct behavior)
```

### Position Size Validation
Trades are validated before execution:
- **Too small**: Skipped (below $1 minimum)
- **Insufficient balance**: Skipped (user can't afford)
- **Invalid symbol**: Skipped (symbol not supported)

## Security & Isolation

### API Key Separation
- Master uses `COINBASE_API_KEY` / `KRAKEN_MASTER_API_KEY`
- Users use `KRAKEN_USER_TANIA_API_KEY` (separate keys)
- **Never shared** between accounts

### Nonce Collision Prevention
- Each broker instance has independent nonce tracking
- Random startup delays prevent simultaneous API calls
- Kraken nonce persistence prevents restarts from causing errors

### Rate Limiting
- Each broker has independent rate limiters
- User A's rate limit doesn't affect User B
- Master rate limit doesn't affect users

## Troubleshooting

### "No user trades appearing"
**Check:**
1. Are user credentials set in environment variables?
2. Did users connect successfully? (check logs for "USER:xxx connected")
3. Is copy engine running? (check logs for "Copy trade engine started")
4. Are trades too small? (minimum $1 USD per trade)

### "User position sizes are wrong"
**Verify:**
1. User balance is accurate
2. Master balance is accurate
3. Position sizing formula: `user_size = master_size * (user_balance / master_balance)`

### "One user always fails"
**Common causes:**
1. Insufficient balance (user can't afford scaled position)
2. Invalid API credentials (check environment variables)
3. API permissions (ensure "Trade" permission is enabled)
4. Minimum position size (user's scaled size < $1)

## Advanced Configuration

### Minimum Position Sizes
Edit `bot/position_sizer.py`:
```python
MIN_POSITION_USD = 1.0  # Change minimum USD value
```

### Copy Engine Queue Size
Edit `bot/trade_signal_emitter.py`:
```python
TradeSignalEmitter(max_queue_size=1000)  # Increase if needed
```

### Supported Exchanges
Currently supported for USER accounts:
- ✅ Kraken (full support)
- ✅ Alpaca (stocks, paper/live)
- ❌ Coinbase (master only, not for users yet)
- ❌ OKX (master only, not for users yet)
- ❌ Binance (master only, not for users yet)

To add support for more exchanges:
1. Implement `account_type` support in broker class
2. Add credential environment variable mapping
3. Test with user account

## Benefits of Copy Trading

### For Users
- ✅ Trade like a pro without expertise
- ✅ Automatic execution (no manual copying)
- ✅ Risk management scales with account size
- ✅ Trades appear in their own exchange dashboard
- ✅ Full control (can close positions anytime)

### For Master Account
- ✅ No changes to trading logic
- ✅ Signals emitted automatically
- ✅ No performance impact (runs in background thread)
- ✅ User failures don't affect master

### For System
- ✅ Scales to unlimited users
- ✅ Broker isolation prevents cascade failures
- ✅ Thread-safe signal queue
- ✅ Comprehensive logging for audit

## Next Steps

1. **Test with paper trading**: Use `ALPACA_USER_TANIA_PAPER=true`
2. **Start with small balances**: Test position sizing accuracy
3. **Monitor logs**: Verify trades are copying correctly
4. **Enable live trading**: Switch to real accounts when confident

## Support

For issues or questions:
1. Check logs for detailed error messages
2. Verify environment variables are set correctly
3. Test with small positions first
4. Review this guide's troubleshooting section

---

**Last Updated**: January 17, 2026
**Version**: NIJA Copy Trading v1.0
