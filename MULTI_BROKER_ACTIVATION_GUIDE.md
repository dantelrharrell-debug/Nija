# Multi-Broker Activation Guide

**Status:** ✅ ACTIVATED - All brokerages are now enabled!

---

## What Changed

NIJA has been upgraded from single-broker mode (Coinbase only) to **multi-broker mode**, which attempts to connect to all supported exchanges simultaneously.

### Supported Brokers

The bot will now try to connect to:

1. **Coinbase Advanced Trade** - Primary crypto exchange
2. **Kraken Pro** - Crypto exchange with lower fees
3. **OKX** - Global crypto exchange
4. **Binance** - World's largest crypto exchange
5. **Alpaca** - Stock trading (US equities)

### Code Changes

**File Modified:** `bot/trading_strategy.py`

**Before:**
```python
# Single broker (Coinbase only)
self.broker = CoinbaseBroker()
if not self.broker.connect():
    logger.warning("Broker connection failed")
```

**After:**
```python
# Multi-broker manager
self.broker_manager = BrokerManager()

# Try connecting all brokers
coinbase = CoinbaseBroker()
if coinbase.connect():
    self.broker_manager.add_broker(coinbase)

kraken = KrakenBroker()
if kraken.connect():
    self.broker_manager.add_broker(kraken)

okx = OKXBroker()
if okx.connect():
    self.broker_manager.add_broker(okx)

binance = BinanceBroker()
if binance.connect():
    self.broker_manager.add_broker(binance)

alpaca = AlpacaBroker()
if alpaca.connect():
    self.broker_manager.add_broker(alpaca)
```

---

## How It Works

### Broker Connection

When the bot starts, it attempts to connect to **all** configured brokers:

1. Checks for API credentials in environment variables (`.env` file)
2. Attempts connection to each exchange
3. Adds successfully connected brokers to the `BrokerManager`
4. Logs which brokers are active
5. Calculates total balance across all exchanges

### Primary Broker

For backward compatibility with existing code, the bot sets a **primary broker**:

- **Preferred:** Coinbase (if connected)
- **Fallback:** First successfully connected broker

The primary broker is used for:
- APEX strategy execution
- Position tracking
- Position cap enforcement

### Multi-Broker Benefits

1. **Redundancy:** If one exchange has API issues, trading continues on others
2. **Diversification:** Balance across multiple exchanges reduces risk
3. **Market Access:** Trade more symbols across different exchanges
4. **Better Pricing:** Can use exchange with best pricing/liquidity
5. **Lower Fees:** Route to exchanges with lower fee structures

---

## Required Credentials

For each broker to connect, you need API credentials in your `.env` file:

### Coinbase Advanced Trade
```bash
COINBASE_API_KEY=organizations/xxx/apiKeys/yyy
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\nMHc...
```

### Kraken Pro
```bash
KRAKEN_API_KEY=your_kraken_api_key
KRAKEN_API_SECRET=your_kraken_api_secret
```

### OKX
```bash
OKX_API_KEY=your_okx_api_key
OKX_API_SECRET=your_okx_api_secret
OKX_PASSPHRASE=your_passphrase
OKX_USE_TESTNET=false
```

### Binance
```bash
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
```

### Alpaca
```bash
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret
APCA_API_BASE_URL=https://paper-api.alpaca.markets  # or live URL
```

---

## Startup Log Output

When the bot starts with multi-broker mode, you'll see:

```
======================================================================
🌐 MULTI-BROKER MODE ACTIVATED
======================================================================
📊 Attempting to connect Coinbase Advanced Trade...
   ✅ Coinbase connected
📊 Attempting to connect Kraken Pro...
   ✅ Kraken connected
📊 Attempting to connect OKX...
   ⚠️  OKX connection failed
📊 Attempting to connect Binance...
   ⚠️  Binance connection failed
📊 Attempting to connect Alpaca...
   ⚠️  Alpaca connection failed
======================================================================
✅ CONNECTED BROKERS: Coinbase, Kraken
💰 TOTAL BALANCE ACROSS ALL BROKERS: $157.42
======================================================================
📌 Primary broker set to: coinbase
```

### What Each Status Means

- ✅ **Connected** - API credentials valid, exchange API is responding
- ⚠️ **Connection failed** - Missing credentials or invalid API keys
- ⚠️ **Error** - Network issue or exchange API down

---

## Current Credentials Status

Based on your `.env` file:

| Broker | Status | Notes |
|--------|--------|-------|
| **Coinbase** | ✅ Configured | Primary exchange, will connect |
| **Kraken** | ✅ Configured | Will attempt connection |
| **OKX** | ⚠️ Partial | Credentials present but may need verification |
| **Binance** | ❌ Not Configured | No credentials found |
| **Alpaca** | ❌ Not Configured | No credentials found |

---

## How Trading Works

### Market Symbol Routing

The `BrokerManager` automatically routes orders to the appropriate exchange:

**Crypto Pairs (BTC-USD, ETH-USD, etc.):**
- Routes to first available crypto broker (Coinbase, Kraken, OKX, or Binance)
- Prefers broker with best liquidity/fees

**Stock Symbols (AAPL, TSLA, etc.):**
- Routes to Alpaca (if connected)
- Falls back to other brokers that support stocks

### Order Placement Example

```python
# Old way (single broker)
self.broker.place_market_order("BTC-USD", "buy", 10.0)

# Still works! Uses primary broker for compatibility
self.broker.place_market_order("BTC-USD", "buy", 10.0)

# New way (multi-broker routing)
self.broker_manager.place_order("BTC-USD", "buy", 10.0)
# Automatically routes to best available crypto broker
```

### Position Tracking

```python
# Get positions from ALL connected brokers
all_positions = self.broker_manager.get_all_positions()

# Each position includes 'broker' field:
# {
#   'symbol': 'BTC-USD',
#   'quantity': 0.001,
#   'broker': 'coinbase'
# }
```

### Total Balance

```python
# Get combined balance across all brokers
total = self.broker_manager.get_total_balance()
```

---

## Setting Up Additional Brokers

### 1. Get API Credentials

Visit each exchange to create API keys:

- **Kraken:** https://www.kraken.com/u/security/api
- **OKX:** https://www.okx.com/account/my-api
- **Binance:** https://www.binance.com/en/my/settings/api-management
- **Alpaca:** https://app.alpaca.markets/paper/dashboard/overview

### 2. Required Permissions

When creating API keys, enable:

✅ **Read permissions:**
- Query account balance
- Query positions
- Query order history

✅ **Trade permissions:**
- Create orders
- Cancel orders

❌ **DO NOT enable:**
- Withdrawal permissions (for security)
- Account management

### 3. Add to .env File

Add credentials to your `.env` file:

```bash
# Kraken
KRAKEN_API_KEY=your_key_here
KRAKEN_API_SECRET=your_secret_here

# OKX
OKX_API_KEY=your_key_here
OKX_API_SECRET=your_secret_here
OKX_PASSPHRASE=your_passphrase
OKX_USE_TESTNET=false

# Binance
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here

# Alpaca
ALPACA_API_KEY=your_key_here
ALPACA_API_SECRET=your_secret_here
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

### 4. Restart the Bot

```bash
# If running locally
./start.sh

# If deployed (Railway/Render)
# Just push changes, platform will auto-redeploy
git add .env
git commit -m "Add multi-broker credentials"
git push
```

---

## Verification

### Check Connected Brokers

Run the diagnostic script:

```bash
python3 check_kraken_connection_status.py
```

Or check the bot startup logs for:
```
✅ CONNECTED BROKERS: Coinbase, Kraken, OKX
```

### View All Positions

The bot will log positions from all brokers:

```
📊 Current positions (across all brokers):
  1. BTC-USD: 0.001 BTC (coinbase)
  2. ETH-USD: 0.05 ETH (kraken)
  3. SOL-USD: 2.5 SOL (coinbase)
```

### Check Total Balance

Logs will show combined balance:
```
💰 Total account balance: $157.42
   - Coinbase: $100.00
   - Kraken: $50.00
   - OKX: $7.42
```

---

## Troubleshooting

### "No brokers connected"

**Cause:** No valid API credentials in `.env`

**Fix:**
1. Check `.env` file exists in project root
2. Verify credentials are correct (no extra spaces)
3. Ensure credentials have proper permissions
4. Test credentials manually on exchange website

### "Broker connection failed: Invalid API key"

**Cause:** Credentials are incorrect or expired

**Fix:**
1. Regenerate API keys on the exchange
2. Update `.env` with new credentials
3. Restart bot

### "Broker connection failed: Permission denied"

**Cause:** API key doesn't have required trading permissions

**Fix:**
1. Go to exchange API settings
2. Enable "Trading" or "Create Orders" permission
3. Save changes
4. Restart bot

### One broker fails but others work

**This is normal!** The bot will use whatever brokers successfully connect.

Example:
```
✅ Coinbase connected
✅ Kraken connected
⚠️  OKX connection failed  # ← This is OK!
⚠️  Binance connection failed  # ← This is OK!
```

Bot will trade on Coinbase and Kraken.

---

## Safety Notes

### Position Limits Still Apply

Even with multiple brokers, the **8-position limit is enforced globally**:

- Maximum 8 positions across ALL brokers combined
- If you have 5 positions on Coinbase and 3 on Kraken = 8 total
- Bot won't open new positions until count drops below 8

### Risk Management

Multi-broker trading increases complexity:

⚠️ **Monitor carefully:**
- Different exchanges have different fee structures
- Prices can vary slightly between exchanges
- API rate limits vary by exchange
- Some exchanges may have maintenance windows

✅ **Best practices:**
- Start with 1-2 brokers until comfortable
- Keep majority of funds on your preferred exchange
- Monitor all exchange accounts regularly
- Set up 2FA on all exchange accounts

### API Key Security

🔒 **Critical security reminders:**

- Never share API keys
- Never commit `.env` to git (it's in `.gitignore`)
- Use API keys with minimal permissions
- Rotate keys regularly (every 90 days)
- Disable withdrawal permissions on trading keys
- Enable IP whitelist if available on exchange

---

## Rollback Instructions

If you want to go back to single-broker (Coinbase only) mode:

### Option 1: Remove Other Credentials

Edit `.env` and remove/comment out non-Coinbase credentials:

```bash
# Keep Coinbase
COINBASE_API_KEY=...
COINBASE_API_SECRET=...

# Comment out others
# KRAKEN_API_KEY=...
# KRAKEN_API_SECRET=...
```

Bot will only connect to Coinbase.

### Option 2: Revert Code Changes

```bash
# Revert to previous version
git checkout 0a0f2ee -- bot/trading_strategy.py
git commit -m "Revert to single-broker mode"
git push
```

---

## Related Files

- **Trading Strategy:** `bot/trading_strategy.py` (modified)
- **Broker Manager:** `bot/broker_manager.py` (classes for all brokers)
- **Coinbase Broker:** `bot/broker_manager.py:1847`
- **Kraken Broker:** `bot/broker_manager.py:2362`
- **OKX Broker:** `bot/broker_manager.py:2681`
- **Binance Broker:** `bot/broker_manager.py:2077`
- **Alpaca Broker:** `bot/broker_manager.py:1947`
- **Environment Config:** `.env`

---

## Summary

✅ **Multi-broker mode is now active**

The bot will automatically:
1. Connect to all configured exchanges
2. Use primary broker (Coinbase preferred) for main strategy
3. Track positions across all exchanges
4. Calculate total balance from all brokers
5. Log which brokers are active/inactive

**What you need to do:**
- Nothing! If you only have Coinbase credentials, it works like before
- Optionally: Add credentials for other exchanges to activate them
- Monitor startup logs to see which brokers connected

**Current connected brokers:** Check startup logs for details
