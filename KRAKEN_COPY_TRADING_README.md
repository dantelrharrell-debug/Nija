# Kraken Copy Trading System

## Overview

The Kraken Copy Trading System enables automatic replication of trades from a MASTER account to multiple USER accounts. When the MASTER account executes a trade, the system automatically:

1. Places the same trade on the MASTER account
2. Scales the position size for each USER based on their balance
3. Places the scaled trade on each USER account
4. Applies safety limits to protect user capital

## Architecture

```
Kraken MASTER
 ├─ Strategy decides trade
 ├─ MASTER places real order
 ├─ Emits trade signal
 └─ Copy Engine
      ├─ Loops Kraken USERS
      ├─ Scales position size (balance ratio)
      ├─ Applies MAX_USER_RISK (10%)
      └─ Places SAME order on each user account
```

**Result:**
- ✅ Trades appear in MASTER Kraken UI
- ✅ Trades appear in EVERY USER Kraken UI

## Features

### Thread-Safe Nonce Management
- Each account (master + users) has its own `NonceStore`
- Nonces are persisted to disk across restarts
- Uses `threading.RLock` for reentrant locking
- Prevents "Invalid nonce" errors

### Balance-Based Position Scaling
- User positions are scaled proportionally to master
- Formula: `user_size = master_size * (user_balance / master_balance)`
- Ensures users trade within their means

### Safety Guards

#### MAX_USER_RISK (10%)
Limits each user trade to 10% of their account balance:
```python
MAX_USER_RISK = 0.10  # 10% max per trade
if user_size > user_balance * MAX_USER_RISK:
    user_size = user_balance * MAX_USER_RISK
```

#### SYSTEM_DISABLED Kill Switch
Global flag to halt all trading:
```python
SYSTEM_DISABLED = False  # Set to True to stop all trades
```

### Error Handling
- Per-user error handling - one user's failure doesn't block others
- Comprehensive logging for debugging
- Graceful degradation if copy trading fails

## Setup

### 1. Configure Master Account

Set environment variables for the MASTER account:

```bash
# Master account credentials
KRAKEN_MASTER_API_KEY=<your-master-api-key>
KRAKEN_MASTER_API_SECRET=<your-master-api-secret>
```

**Or** use legacy credentials (backward compatible):
```bash
KRAKEN_API_KEY=<your-master-api-key>
KRAKEN_API_SECRET=<your-master-api-secret>
```

### 2. Configure User Accounts

Edit `config/users/retail_kraken.json`:

```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  },
  {
    "user_id": "tania_gilbert",
    "name": "Tania Gilbert",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  }
]
```

Set environment variables for each user:

```bash
# For user_id "daivon_frazier" (uses first part before underscore)
KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>

# For user_id "tania_gilbert"
KRAKEN_USER_TANIA_API_KEY=<tania-api-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>
```

### 3. Kraken API Permissions

Each API key (master + users) needs these permissions:
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders

**DO NOT** enable:
- ❌ Withdraw Funds (security risk)

### 4. Bot Integration

The copy trading system is automatically initialized when the bot starts if:
1. Master credentials are configured
2. At least one user is configured and enabled
3. Kraken master broker connects successfully

No code changes needed - the integration is automatic via `trading_strategy.py`.

## Usage

### Automatic Mode (Recommended)

Simply run the bot normally. Copy trading activates automatically when:
- MASTER Kraken broker connects
- Copy trading system initializes successfully

```bash
python bot.py
# or
python start.sh
```

**Logs to watch for:**
```
🚀 INITIALIZING KRAKEN COPY TRADING SYSTEM
✅ Kraken MASTER client initialized
✅ Initialized user: Daivon Frazier (daivon_frazier) - Balance: $1000.00
✅ Initialized user: Tania Gilbert (tania_gilbert) - Balance: $500.00
✅ KRAKEN COPY TRADING SYSTEM READY
   MASTER: Initialized
   USERS: 2 ready for copy trading
✅ Kraken broker wrapped for copy trading: MASTER
```

### Manual Mode (Advanced)

For testing or custom integration:

```python
from bot.kraken_copy_trading import (
    initialize_copy_trading_system,
    execute_master_trade
)

# Initialize system
if initialize_copy_trading_system():
    # Execute a trade manually
    execute_master_trade(
        pair="XXBTZUSD",    # BTC/USD
        side="buy",          # or "sell"
        usd_size=100.0       # $100 order
    )
```

## Trading Flow Example

### MASTER executes $1000 BTC buy:

1. **Master Balance:** $10,000
2. **User 1 Balance:** $1,000 (10% of master)
3. **User 2 Balance:** $500 (5% of master)

**Execution:**

```
MASTER: Buy $1000 BTC ✅
  └─ Order placed on MASTER Kraken account

USER 1: Scaled to $100 (1000 * 1000/10000)
  └─ $100 < 10% of $1000 = $100 ✅
  └─ Buy $100 BTC on User 1 account

USER 2: Scaled to $50 (1000 * 500/10000)
  └─ $50 < 10% of $500 = $50 ✅
  └─ Buy $50 BTC on User 2 account
```

### Safety Limit Example

**User 1 Balance:** $100
**Master Trade:** $1000 BTC buy
**Scaled Size:** $10 (1000 * 100/10000)
**Max Allowed (10%):** $10
**Result:** ✅ Trade executes at $10 (within limit)

**If scaled was $15:**
**Result:** ⚠️ Capped to $10 (10% limit applied)

## Monitoring

### Trade Logs

Each trade generates detailed logs:

```
🟢 EXECUTING MASTER TRADE | XXBTZUSD | BUY | $100.00
✅ MASTER KRAKEN TRADE EXECUTED
   Pair: XXBTZUSD
   Side: BUY
   Order ID: O1234567890
   Size: $100.00 (0.00100000 XBTZUSD)

🔄 COPY TRADING TO 2 USERS
   🔄 Copying to Daivon Frazier (daivon_frazier)...
      Balance: $1000.00
      Size: $10.00 (0.00010000)
      ✅ COPY SUCCESS | Order ID: O9876543210
   
   🔄 Copying to Tania Gilbert (tania_gilbert)...
      Balance: $500.00
      Size: $5.00 (0.00005000)
      ✅ COPY SUCCESS | Order ID: O5555555555

📊 COPY TRADING SUMMARY
   Success: 2/2
   Failed: 0/2
```

### Error Handling

If a user trade fails, it's logged but doesn't block other users:

```
🔄 Copying to User X...
   ❌ COPY FAILED: Insufficient balance

📊 COPY TRADING SUMMARY
   Success: 1/2
   Failed: 1/2
```

## Troubleshooting

### User Not Trading

**Check:** User credentials configured?
```bash
echo $KRAKEN_USER_DAIVON_API_KEY
echo $KRAKEN_USER_DAIVON_API_SECRET
```

**Check:** User enabled in config?
```json
{
  "user_id": "daivon_frazier",
  "enabled": true  // Must be true
}
```

**Check:** API permissions?
- Ensure all required permissions are enabled on Kraken

### Nonce Errors

**Symptom:** "Invalid nonce" errors

**Solution:** Nonce files persist across restarts. If you see persistent nonce errors:
1. Stop the bot
2. Delete nonce files: `rm bot/kraken_nonce_*.txt`
3. Restart the bot

The system will regenerate nonces automatically.

### Copy Trading Not Activating

**Check logs for:**
```
❌ Failed to initialize Kraken MASTER - copy trading disabled
```

**Or:**
```
⚠️  No Kraken users initialized - trades will execute on MASTER only
```

**Solutions:**
1. Verify master credentials are set
2. Verify user credentials are set
3. Check `retail_kraken.json` has enabled users
4. Review API permissions

## Security

### Credential Isolation

- Each account has its own API credentials
- Nonce files are account-specific
- No cross-contamination between accounts

### Risk Limits

- **MAX_USER_RISK:** Hard limit at 10% per trade
- **SYSTEM_DISABLED:** Emergency kill switch
- **Per-user error handling:** One failure doesn't cascade

### Best Practices

1. **Use separate API keys** for master and each user
2. **DO NOT enable withdrawal permissions**
3. **Start with small balances** to test
4. **Monitor logs** during initial setup
5. **Use SYSTEM_DISABLED** flag for emergency stops

## Testing

### Unit Tests

```bash
python test_kraken_copy_trading.py
```

Tests:
- ✅ NonceStore functionality
- ✅ KrakenClient initialization
- ✅ MASTER initialization
- ✅ USERS initialization
- ✅ Full system initialization

### Integration Tests

```bash
python test_kraken_copy_integration.py
```

Tests:
- ✅ Import integration
- ✅ Broker wrapper function
- ✅ Safety guards

## Files

### Core Files

- **`bot/kraken_copy_trading.py`** - Main copy trading engine (700+ lines)
- **`bot/trading_strategy.py`** - Integration with trading strategy
- **`config/users/retail_kraken.json`** - User configuration

### Test Files

- **`test_kraken_copy_trading.py`** - Unit tests
- **`test_kraken_copy_integration.py`** - Integration tests

### Generated Files (Runtime)

- **`bot/kraken_nonce_master.txt`** - Master nonce persistence
- **`bot/kraken_nonce_user_<user_id>.txt`** - Per-user nonce files

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review logs for error messages
3. Verify all credentials and permissions
4. Test with small balances first
5. Use SYSTEM_DISABLED flag to halt trading if needed

## License

Same as main NIJA project.
