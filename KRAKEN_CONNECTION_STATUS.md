# NIJA Kraken Pro Connection Status

**Last Updated:** December 30, 2025

---

## ❌ ANSWER: NO - NIJA IS NOT CONNECTED TO KRAKEN PRO

NIJA is currently connected to **Coinbase Advanced Trade**, not Kraken Pro. All trades are being made through your Coinbase account (dantelrharrell@gmail.com).

---

## Current Configuration

### Active Broker
- **Broker:** Coinbase Advanced Trade API
- **Account:** dantelrharrell@gmail.com
- **Code Location:** `bot/trading_strategy.py` (line 131)
- **Implementation:** `self.broker = CoinbaseBroker()`

### Kraken Status
- **Integration Code:** ✅ Present and complete in `bot/broker_manager.py`
- **Credentials:** ✅ Present in `.env` file
  - `KRAKEN_API_KEY`: Set (56 characters)
  - `KRAKEN_API_SECRET`: Set (88 characters)
- **Connection Test:** ⚠️ Cannot verify (network restrictions in sandbox environment)
- **Active Status:** ❌ Not being used by the bot

---

## How NIJA Currently Works

1. **Broker Initialization:** When the bot starts, it creates a `CoinbaseBroker()` instance
2. **Market Scanning:** Scans 732+ cryptocurrency markets on Coinbase
3. **Trade Execution:** All buy/sell orders go through Coinbase Advanced Trade API
4. **Position Management:** Tracks positions via Coinbase API
5. **Balance Checks:** Queries Coinbase account balance

**All trading activity is on Coinbase, NOT Kraken.**

---

## Kraken Integration Details

### What's Already Built

The codebase includes a complete Kraken Pro integration that is **ready to use** but **currently disabled**:

**Features Available:**
- ✅ Full Kraken Pro API integration (`bot/broker_manager.py`, class `KrakenBroker`)
- ✅ Spot trading support (USD/USDT pairs)
- ✅ Market and limit orders
- ✅ Real-time account balance fetching
- ✅ Historical candle data (OHLCV)
- ✅ Position tracking
- ✅ Order execution and management

**Dependencies Installed:**
- `krakenex==2.2.2` - Kraken API wrapper
- `pykrakenapi==0.3.2` - Enhanced Kraken API interface

### Why It's Not Active

In `bot/apex_live_trading.py` (lines 323-325), the Kraken initialization is **commented out**:

```python
# Optional: Add Kraken Pro for crypto
# kraken = KrakenBroker()
# if kraken.connect():
#     broker_manager.add_broker(kraken)
```

This shows the integration was developed but not activated for production use.

---

## How to Switch to Kraken Pro (If Desired)

### ⚠️ Important Warning

Before switching brokers:
1. **Close all Coinbase positions** - The bot cannot manage positions across different brokers
2. **Verify Kraken account is funded** - Ensure you have USD/USDT balance on Kraken
3. **Test credentials** - Make sure your Kraken API keys have proper permissions
4. **Understand the change** - This will completely change where trades execute

### Step-by-Step Process

#### 1. Verify Kraken Credentials

Check that your `.env` file has valid Kraken API credentials:

```bash
KRAKEN_API_KEY=your_kraken_api_key_here
KRAKEN_API_SECRET=your_kraken_api_secret_here
```

Get credentials from: https://www.kraken.com/u/security/api

**Required API Permissions:**
- Query Funds
- Query Open Orders & Trades
- Query Closed Orders & Trades
- Create & Modify Orders
- Cancel/Close Orders

#### 2. Test Kraken Connection

Run the status checker to verify your credentials work:

```bash
python3 check_kraken_connection_status.py
```

You should see:
- ✅ Kraken credentials are valid
- ✅ Successfully connected to Kraken Pro
- Your Kraken account balance should display

#### 3. Modify Bot Code

Edit `bot/trading_strategy.py`:

**Current code (line 131):**
```python
self.broker = CoinbaseBroker()
```

**Change to:**
```python
self.broker = KrakenBroker()
```

**Also add the import at the top of the file:**

Find the import section and add:
```python
from broker_manager import CoinbaseBroker, KrakenBroker
```

Or change the existing import from:
```python
from broker_manager import CoinbaseBroker
```

To:
```python
from broker_manager import CoinbaseBroker, KrakenBroker
```

#### 4. Update Position Manager Reference

Also in `bot/trading_strategy.py` (line 136), the position enforcer uses the broker:

```python
self.enforcer = PositionCapEnforcer(max_positions=8, broker=self.broker)
```

This should automatically use the Kraken broker after your change in step 3.

#### 5. Test Locally (Recommended)

Before deploying to production:

```bash
# Install dependencies if needed
pip install -r requirements.txt

# Test the bot startup
python3 bot.py
```

Watch the logs for:
- "✅ KRAKEN PRO CONNECTED"
- Kraken balance display
- No errors about missing credentials

#### 6. Deploy to Production

Once tested locally:

```bash
git add bot/trading_strategy.py
git commit -m "Switch from Coinbase to Kraken Pro broker"
git push
```

Your deployment platform (Railway/Render) will automatically redeploy with the changes.

#### 7. Monitor the Switch

After deployment:
- Check logs for successful Kraken connection
- Verify balance is being read correctly
- Watch first few trades to ensure they execute on Kraken
- Monitor for any API errors

---

## Key Differences: Coinbase vs Kraken

### Market Data
- **Coinbase:** 732+ cryptocurrency pairs
- **Kraken:** Different set of crypto pairs (overlap but not identical)

### Trading Fees
- **Coinbase Advanced Trade:** ~0.5-1.5% (tiered)
- **Kraken Pro:** ~0.16-0.26% (tiered, generally lower)

### API Differences
- **Symbol Format:**
  - Coinbase: `BTC-USD`, `ETH-USD`
  - Kraken: `XBTUSD`, `ETHUSD` (no dash, BTC = XBT)
- **Balance Naming:**
  - Coinbase: `USD`
  - Kraken: `ZUSD` for USD, `USDT` for Tether

The `KrakenBroker` class handles these differences automatically.

---

## Multi-Broker Setup (Advanced)

The codebase also supports using **both brokers simultaneously** through the `BrokerManager` class:

```python
from broker_manager import BrokerManager, CoinbaseBroker, KrakenBroker

# Create broker manager
broker_manager = BrokerManager()

# Add Coinbase
coinbase = CoinbaseBroker()
if coinbase.connect():
    broker_manager.add_broker(coinbase)

# Add Kraken
kraken = KrakenBroker()
if kraken.connect():
    broker_manager.add_broker(kraken)

# Bot can now trade on both exchanges
```

This is more complex and would require significant modifications to the trading strategy.

---

## Verification Script

A diagnostic script has been created to check the current broker status:

```bash
python3 check_kraken_connection_status.py
```

This script will:
- ✅ Show which broker is currently active
- ✅ Check if Kraken credentials are configured
- ✅ Test Kraken API connection (if credentials exist)
- ✅ Display Kraken account balance
- ✅ Provide summary and recommendations

---

## Troubleshooting

### "Kraken connection failed: Invalid API key"
- Verify `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` in `.env`
- Check that API key hasn't expired
- Regenerate keys on Kraken if needed

### "Kraken connection failed: Permission denied"
- Check API key permissions on Kraken
- Enable required trading permissions (see Step 1 above)

### "No module named 'krakenex'"
- Install dependencies: `pip install krakenex pykrakenapi`
- Or run: `pip install -r requirements.txt`

### Bot still trading on Coinbase after code change
- Verify changes were saved to `bot/trading_strategy.py`
- Check that code was committed and pushed
- Verify deployment platform picked up the changes
- Restart the bot/service

---

## Related Files

- **Broker Implementation:** `bot/broker_manager.py` (line 2362: `class KrakenBroker`)
- **Trading Strategy:** `bot/trading_strategy.py` (line 131: broker selection)
- **Live Trading Example:** `bot/apex_live_trading.py` (lines 323-325: commented Kraken setup)
- **Environment Config:** `.env` (Kraken credentials)
- **Dependencies:** `requirements.txt` (krakenex, pykrakenapi)
- **Status Checker:** `check_kraken_connection_status.py` (diagnostic tool)

---

## Summary

**Current Status:**
- ❌ NIJA is NOT connected to Kraken Pro
- ✅ NIJA IS connected to Coinbase Advanced Trade
- ✅ Kraken integration code is ready but not active
- ✅ Kraken credentials are configured

**To Use Kraken:**
1. Close all Coinbase positions
2. Test Kraken credentials
3. Modify `bot/trading_strategy.py` to use `KrakenBroker()`
4. Deploy and monitor

**Current Account:**
- All trades are on Coinbase (dantelrharrell@gmail.com)
- No trades are being made on Kraken

---

For more information, see:
- Kraken API Documentation: https://docs.kraken.com/rest/
- Kraken Security Settings: https://www.kraken.com/u/security/api
- NIJA Documentation: `README.md`, `BROKER_INTEGRATION_GUIDE.md`
