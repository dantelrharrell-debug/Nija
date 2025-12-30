# 🚀 OKX Quick Reference Card

Quick copy-paste commands and code snippets for OKX integration.

## ⚡ Installation (One Command)

```bash
pip install okx && cp .env.example .env
```

Then edit `.env` and add your OKX credentials.

## 🔑 Environment Variables

```bash
# Add to .env file
OKX_API_KEY=your_api_key_here
OKX_API_SECRET=your_secret_key_here
OKX_PASSPHRASE=your_passphrase_here
OKX_USE_TESTNET=true  # Set to false for live trading
```

## ✅ Test Connection

```bash
python test_okx_connection.py
```

## 📝 Basic Usage Examples

### Example 1: Simple Connection Test

```python
from bot.broker_manager import OKXBroker

okx = OKXBroker()
if okx.connect():
    balance = okx.get_account_balance()
    print(f"Balance: ${balance:.2f}")
```

### Example 2: Get Market Data

```python
from bot.broker_manager import OKXBroker

okx = OKXBroker()
okx.connect()

# Get BTC-USDT candles (5-minute, last 100)
candles = okx.get_candles('BTC-USDT', '5m', 100)

# Show latest price
if candles:
    latest = candles[0]
    print(f"BTC Price: ${latest['close']:.2f}")
```

### Example 3: Place Market Order

```python
from bot.broker_manager import OKXBroker

okx = OKXBroker()
okx.connect()

# Buy $10 worth of BTC
order = okx.place_market_order('BTC-USDT', 'buy', 10.0)
print(f"Order ID: {order['order_id']}")
```

### Example 4: Check Positions

```python
from bot.broker_manager import OKXBroker

okx = OKXBroker()
okx.connect()

# Get all open positions
positions = okx.get_positions()
for pos in positions:
    print(f"{pos['symbol']}: {pos['quantity']:.6f}")
```

### Example 5: Using BrokerFactory (Recommended)

```python
from bot.broker_integration import BrokerFactory

# Create OKX broker
okx = BrokerFactory.create_broker('okx', testnet=True)

if okx.connect():
    # Auto-converts BTC-USD to BTC-USDT
    data = okx.get_market_data('BTC-USD', '5m', 100)
    
    balance = okx.get_account_balance()
    print(f"Available: ${balance['available_balance']:.2f}")
```

## 🎯 Symbol Format

| You Use | OKX Converts To |
|---------|----------------|
| BTC-USD | BTC-USDT |
| ETH-USD | ETH-USDT |
| SOL-USD | SOL-USDT |
| BTC-USDT | BTC-USDT (no change) |

## ⏰ Timeframes

| Code | Interval |
|------|----------|
| `1m` | 1 minute |
| `5m` | 5 minutes |
| `15m` | 15 minutes |
| `1H` | 1 hour |
| `4H` | 4 hours |
| `1D` | 1 day |

## 🛡️ Common Issues & Quick Fixes

### "Invalid signature"
```bash
# Double-check credentials - no spaces!
cat .env | grep OKX
```

### "Insufficient balance"
```bash
# Check your balance
python -c "from bot.broker_manager import OKXBroker; b=OKXBroker(); b.connect(); print(b.get_account_balance())"
```

### "Module not found: okx"
```bash
pip install okx
```

### "Order size too small"
```python
# Minimum order: ~$5-10 USD
okx.place_market_order('BTC-USDT', 'buy', 10.0)  # Use at least $10
```

## 📊 Integration with NIJA Strategy

```python
from bot.broker_manager import OKXBroker
from bot.trading_strategy import TradingStrategy

# Initialize OKX
okx = OKXBroker()
okx.connect()

# Get balance
balance = okx.get_account_balance()

# Initialize trading strategy
strategy = TradingStrategy(okx, balance)

# Scan for opportunities
markets = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT']
for market in markets:
    candles = okx.get_candles(market, '5m', 100)
    # Strategy analysis here...
```

## 🔐 Security Checklist

- [ ] API key stored in `.env` file
- [ ] `.env` added to `.gitignore`
- [ ] Only "Trade" permission enabled (NOT "Withdrawal")
- [ ] IP whitelist configured on OKX
- [ ] Tested on testnet first
- [ ] Started with small amounts ($10-50)

## 📱 Quick Commands

```bash
# Check OKX is configured
grep OKX .env

# Test connection
python test_okx_connection.py

# Check balance from command line
python -c "from bot.broker_manager import OKXBroker; b=OKXBroker(); b.connect(); print(f'${b.get_account_balance():.2f}')"

# Check supported brokers
python -c "from bot.apex_config import BROKERS; print(BROKERS['supported'])"
```

## 🔗 Useful Links

- **Setup Guide**: [OKX_SETUP_GUIDE.md](OKX_SETUP_GUIDE.md)
- **Integration Guide**: [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md)
- **OKX API Docs**: https://www.okx.com/docs-v5/en/
- **OKX Testnet**: https://www.okx.com/testnet
- **Get API Keys**: https://www.okx.com/account/my-api

## 💡 Pro Tips

1. **Always start with testnet** - Free virtual money, zero risk
2. **Small orders first** - Test with $10-20 before scaling up
3. **Monitor logs** - Check for errors: `grep OKX bot.log`
4. **IP whitelist** - Extra security layer on OKX website
5. **Never share keys** - Keep credentials private
6. **Regular backups** - Save your `.env` file securely (but never in git!)

---

**Need help?** See [OKX_SETUP_GUIDE.md](OKX_SETUP_GUIDE.md) for detailed instructions.
