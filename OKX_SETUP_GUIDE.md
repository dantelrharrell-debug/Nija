# OKX Exchange Setup Guide for NIJA

This guide will walk you through connecting NIJA to OKX Exchange step by step.

## 📋 Prerequisites

- NIJA bot installed and working
- OKX account created at https://www.okx.com
- Python 3.11+ with pip

## 🔐 Step 1: Create OKX API Credentials

### For Testnet (Recommended First):

1. Go to https://www.okx.com/testnet
2. Sign up for a testnet account (free)
3. Navigate to **Account** → **API**
4. Click **Create API Key**
5. Configure:
   - **API Name**: NIJA Trading Bot
   - **Permissions**: Enable "Trade" only (NOT "Withdrawal")
   - **Passphrase**: Create a strong passphrase (you'll need this)
   - **IP Whitelist**: Add your server IP (optional but recommended)
6. Click **Confirm**
7. **SAVE THESE CREDENTIALS IMMEDIATELY** (you won't see them again):
   - API Key
   - Secret Key
   - Passphrase

### For Live Trading:

Follow the same steps but on https://www.okx.com (live site).

⚠️ **IMPORTANT**: Never enable "Withdrawal" permission for trading bots!

## ⚙️ Step 2: Install OKX SDK

```bash
cd /path/to/Nija
pip install okx
```

Or update all dependencies:

```bash
pip install -r requirements.txt
```

## 🔧 Step 3: Configure Environment Variables

### Option A: Using .env file (Recommended)

1. Copy the example file:
```bash
cp .env.example .env
```

2. Edit `.env` and add your OKX credentials:
```bash
# OKX Exchange API Credentials
OKX_API_KEY=your_api_key_here
OKX_API_SECRET=your_secret_key_here
OKX_PASSPHRASE=your_passphrase_here
OKX_USE_TESTNET=true  # Set to false for live trading
```

3. Save the file

### Option B: Export environment variables

```bash
export OKX_API_KEY="your_api_key_here"
export OKX_API_SECRET="your_secret_key_here"
export OKX_PASSPHRASE="your_passphrase_here"
export OKX_USE_TESTNET="true"  # Set to false for live trading
```

## ✅ Step 4: Test the Connection

Run the test script:

```bash
python test_okx_connection.py
```

Expected output:
```
🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥
   OKX EXCHANGE INTEGRATION TEST
🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

======================================================================
OKX CREDENTIAL CHECK
======================================================================

📋 Configuration Status:
   OKX_API_KEY: ✅ Set
   OKX_API_SECRET: ✅ Set
   OKX_PASSPHRASE: ✅ Set
   OKX_USE_TESTNET: true

======================================================================
TEST 1: OKX Integration via broker_manager.py
======================================================================

🔌 Connecting to OKX...
======================================================================
✅ OKX CONNECTED (🧪 TESTNET)
======================================================================
   Total Account Value: $10000.00
======================================================================
✅ Successfully connected to OKX!

💰 Fetching account balance...
   USDT Balance: $10000.00

📊 Fetching open positions...
   No open positions

📈 Fetching market data for BTC-USDT...
   Fetched 10 candles
   Latest candle: O=43250.50, H=43300.00, L=43200.00, C=43280.75

======================================================================
TEST SUMMARY
======================================================================
   broker_manager.py: ✅ PASSED
   broker_integration.py: ✅ PASSED

✅ All tests passed! OKX integration is working correctly.
```

## 🚀 Step 5: Using OKX with NIJA

### Method 1: Using BrokerManager (Recommended)

```python
from bot.broker_manager import OKXBroker

# Initialize OKX broker
okx = OKXBroker()

# Connect
if okx.connect():
    print("✅ Connected to OKX")
    
    # Get balance
    balance = okx.get_account_balance()
    print(f"USDT Balance: ${balance:.2f}")
    
    # Get market data
    candles = okx.get_candles('BTC-USDT', '5m', 100)
    
    # Place a buy order
    order = okx.place_market_order('BTC-USDT', 'buy', 10.0)  # $10 USDT
    print(f"Order ID: {order['order_id']}")
```

### Method 2: Using BrokerFactory (Adapter Pattern)

```python
from bot.broker_integration import BrokerFactory

# Create OKX broker
okx = BrokerFactory.create_broker('okx', testnet=True)

# Connect and trade
if okx.connect():
    # Get balance
    balance = okx.get_account_balance()
    print(f"Available: ${balance['available_balance']:.2f}")
    
    # Get market data (auto-converts BTC-USD to BTC-USDT)
    data = okx.get_market_data('BTC-USD', '5m', 100)
    
    # Place order
    order = okx.place_market_order('BTC-USD', 'buy', 10.0)
```

### Method 3: Multi-Broker Setup

```python
from bot.broker_manager import CoinbaseBroker, OKXBroker, BrokerManager

# Initialize brokers
manager = BrokerManager()

# Add Coinbase
coinbase = CoinbaseBroker()
if coinbase.connect():
    manager.add_broker(coinbase)

# Add OKX
okx = OKXBroker()
if okx.connect():
    manager.add_broker(okx)

# Get total balance across all exchanges
total = manager.get_total_balance()
print(f"Total across all exchanges: ${total:.2f}")

# Get all positions
positions = manager.get_all_positions()
for pos in positions:
    print(f"{pos['broker']}: {pos['symbol']} - {pos['quantity']}")
```

## 🎯 Trading on OKX

### Symbol Format

OKX uses USDT pairs:
- ✅ Correct: `BTC-USDT`, `ETH-USDT`, `SOL-USDT`
- ❌ Wrong: `BTC-USD`, `ETH-USD` (these work but get auto-converted)

### Supported Trading Pairs

OKX supports 400+ crypto trading pairs. Popular ones:
- Major: BTC-USDT, ETH-USDT, BNB-USDT
- DeFi: UNI-USDT, AAVE-USDT, LINK-USDT
- Layer 1: SOL-USDT, AVAX-USDT, MATIC-USDT
- Layer 2: ARB-USDT, OP-USDT

### Order Types

**Market Orders** (Immediate execution):
```python
okx.place_market_order('BTC-USDT', 'buy', 50.0)  # Buy $50 worth
okx.place_market_order('BTC-USDT', 'sell', 0.001)  # Sell 0.001 BTC
```

**Limit Orders** (Execute at specific price):
```python
# Not yet fully implemented - coming soon
```

### Timeframes for Candle Data

Supported intervals:
- Minutes: `1m`, `3m`, `5m`, `15m`, `30m`
- Hours: `1H`, `2H`, `4H`, `6H`, `12H`
- Days: `1D`, `1W`, `1M`

Example:
```python
candles = okx.get_candles('ETH-USDT', '5m', 100)
for candle in candles[:5]:
    print(f"Close: ${candle['close']:.2f}, Volume: {candle['volume']:.2f}")
```

## 🛡️ Security Best Practices

### API Key Security
1. ✅ **DO**: Store credentials in `.env` file
2. ✅ **DO**: Add `.env` to `.gitignore`
3. ✅ **DO**: Enable only "Trade" permission
4. ✅ **DO**: Use IP whitelist
5. ❌ **DON'T**: Enable "Withdrawal" permission
6. ❌ **DON'T**: Commit credentials to git
7. ❌ **DON'T**: Share API keys publicly

### Testing Strategy
1. Start with **testnet** (free virtual money)
2. Test all features thoroughly
3. Switch to **live** with small amounts ($10-50)
4. Gradually increase position sizes
5. Monitor closely for first 24-48 hours

### Risk Management
```python
# Set conservative limits for testing
MAX_POSITION_SIZE = 0.02  # 2% of balance
BASE_TRADE_SIZE = 10.0    # $10 per trade
STOP_LOSS_PCT = 0.02      # 2% stop loss
```

## 🔧 Troubleshooting

### "Invalid signature" Error
**Cause**: Incorrect API credentials
**Fix**:
1. Double-check API key, secret, and passphrase
2. Ensure no extra spaces in `.env` file
3. Verify you're using the correct environment (testnet vs live)

### "Insufficient balance" Error
**Cause**: Not enough USDT in trading account
**Fix**:
1. Check balance: `okx.get_account_balance()`
2. On testnet: Request test tokens
3. On live: Transfer funds from funding to trading account

### "Order size too small" Error
**Cause**: Order below minimum notional value
**Fix**: 
- Minimum order size is usually $5-10 USD
- Increase your order size

### "Rate limit exceeded" Error
**Cause**: Too many API calls
**Fix**:
- Add delays between calls: `time.sleep(1)`
- Reduce scan frequency
- Implement exponential backoff

### Import Errors
**Cause**: OKX SDK not installed
**Fix**:
```bash
pip install okx
```

## 📊 Monitoring and Logs

Check OKX-specific logs:
```bash
# See connection status
grep "OKX" bot.log

# See all trades
grep "order placed" bot.log | grep OKX

# See errors
grep "ERROR" bot.log | grep OKX
```

## 🎓 Next Steps

1. ✅ Complete this setup guide
2. ✅ Test connection with `test_okx_connection.py`
3. ✅ Make a small test trade on testnet
4. ✅ Review OKX positions and balance
5. 📖 Read the [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md)
6. 📖 Understand the NIJA [APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)
7. 🚀 Start trading!

## 📚 Additional Resources

- [OKX Official API Docs](https://www.okx.com/docs-v5/en/)
- [OKX Python SDK GitHub](https://github.com/okx/okx-python-sdk)
- [OKX Testnet](https://www.okx.com/testnet)
- [NIJA Broker Integration Guide](BROKER_INTEGRATION_GUIDE.md)

## 💬 Getting Help

If you encounter issues:

1. Check this guide's troubleshooting section
2. Review test output from `test_okx_connection.py`
3. Check OKX API status: https://www.okx.com/status
4. Verify your API permissions on OKX website
5. Check bot logs for error messages

## 🎉 Success Checklist

- [ ] OKX account created
- [ ] API credentials generated
- [ ] Credentials added to `.env` file
- [ ] OKX SDK installed (`pip install okx`)
- [ ] Test script passed (`python test_okx_connection.py`)
- [ ] Test trade executed successfully on testnet
- [ ] Understand symbol format (BTC-USDT)
- [ ] Security best practices reviewed
- [ ] Ready to trade! 🚀

---

**Version**: 1.0  
**Last Updated**: December 30, 2024  
**Compatibility**: NIJA Apex Strategy v7.1+
