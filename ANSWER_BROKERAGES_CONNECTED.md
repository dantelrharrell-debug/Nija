# Quick Answer: What Brokerages Are Connected and Ready to Trade?

## Immediate Answer

Run this command to see what's connected:

```bash
python3 check_broker_status.py
```

Or use the shortcut:
```bash
./check_brokers.sh
```

## What You'll See

The script will show:

1. ✅ **Connected Brokers** - Ready to trade with balance shown
2. ⚠️ **Failed Connections** - Credentials set but can't connect
3. 📝 **Not Configured** - Need API credentials added to .env

## Example Output

### When Coinbase is Connected:
```
✅ 1 BROKER(S) CONNECTED AND READY TO TRADE:
   🟦 Coinbase Advanced Trade [PRIMARY] - $34.54

✅ NIJA IS READY TO TRADE
   Primary Trading Broker: Coinbase Advanced Trade
   Total Available Capital: $34.54
```

### When Multiple Brokers Connected:
```
✅ 3 BROKER(S) CONNECTED AND READY TO TRADE:
   🟦 Coinbase Advanced Trade [PRIMARY] - $157.42
   🟪 Kraken Pro - $50.00
   🟨 Binance - $100.00

💰 Total Combined Balance: $307.42

✅ NIJA IS READY TO TRADE
   Active Brokers: 3
   Trading Capabilities:
      • Cryptocurrency: 3 exchange(s)
   Primary Trading Broker: Coinbase Advanced Trade
```

### When Nothing Connected:
```
❌ NO BROKERS CONNECTED

📝 5 BROKER(S) NOT CONFIGURED:
   🟦 Coinbase Advanced Trade (Crypto)
   🟪 Kraken Pro (Crypto)
   ⬛ OKX (Crypto)
   🟨 Binance (Crypto)
   🟩 Alpaca (Stocks)

❌ NIJA IS NOT READY TO TRADE
   Please configure at least one broker's credentials in the .env file.
```

## Supported Brokers

NIJA supports 5 different brokerages:

| Icon | Broker | Type | Status |
|------|--------|------|--------|
| 🟦 | Coinbase Advanced Trade | Crypto | Primary - Most tested |
| 🟪 | Kraken Pro | Crypto | Fully supported |
| ⬛ | OKX | Crypto | Fully supported |
| 🟨 | Binance | Crypto | Fully supported |
| 🟩 | Alpaca | Stocks | Stocks trading |

## Current Configuration

Based on your .env file, the bot will:
- Try to connect to **all** configured brokers
- Use Coinbase as the **primary** broker (if connected)
- Trade on **any** successfully connected exchange
- Track positions **across all brokers**
- Enforce 8-position limit **across all exchanges combined**

## How It Works

1. **At Startup**: Bot attempts to connect to all brokers with credentials
2. **During Trading**: Routes orders to appropriate broker for each symbol
3. **Position Tracking**: Monitors all positions across all connected exchanges
4. **Balance**: Combines balance from all connected brokers

## Need More Detail?

See the full documentation:
- **Quick Reference**: `BROKER_CONNECTION_STATUS.md`
- **Full Setup Guide**: `BROKER_INTEGRATION_GUIDE.md`
- **Multi-Broker Status**: `MULTI_BROKER_STATUS.md`

---

**Last Updated**: December 30, 2025
