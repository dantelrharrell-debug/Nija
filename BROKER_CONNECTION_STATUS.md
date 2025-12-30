# Broker Connection Status - Quick Reference

## Check Connected Brokers

To see which brokerages are connected and ready to trade, run:

```bash
python3 check_broker_status.py
```

## What It Shows

The status checker displays:

1. **Connected Brokers** ✅ - Fully connected and ready to trade
2. **Failed Connections** ⚠️ - Credentials configured but connection failed  
3. **Not Configured** 📝 - Missing API credentials
4. **Trading Readiness** - Overall status of the bot
5. **Total Balance** 💰 - Combined balance across all connected exchanges

## Example Output

```
================================================================================
  NIJA Multi-Broker Connection Status Report
================================================================================

✅ 2 BROKER(S) CONNECTED AND READY TO TRADE:
   🟦 Coinbase Advanced Trade [PRIMARY] - $157.42
   🟪 Kraken Pro - $50.00

💰 Total Combined Balance: $207.42

📝 3 BROKER(S) NOT CONFIGURED:
   ⬛ OKX (Crypto)
   🟨 Binance (Crypto)
   🟩 Alpaca (Stocks)

✅ NIJA IS READY TO TRADE
   Active Brokers: 2
   Primary Trading Broker: Coinbase Advanced Trade
```

## Supported Brokers

| Broker | Type | Icon | Status |
|--------|------|------|--------|
| Coinbase Advanced Trade | Crypto | 🟦 | Primary |
| Kraken Pro | Crypto | 🟪 | Secondary |
| OKX | Crypto | ⬛ | Secondary |
| Binance | Crypto | 🟨 | Secondary |
| Alpaca | Stocks | 🟩 | Secondary |

## Quick Answers

### "Are any brokers connected?"
Run `python3 check_broker_status.py` and look for the summary section.

### "Which broker is the primary?"
The primary broker is marked with `[PRIMARY]` tag - usually Coinbase.

### "What's my total balance?"
The script shows combined balance across all connected exchanges.

### "Why isn't a broker connecting?"
The script shows error messages for failed connections. Common issues:
- Invalid API credentials
- Insufficient API permissions
- Network connectivity problems
- Testnet vs production mismatch

## Setting Up Additional Brokers

To add a broker:

1. Get API credentials from the exchange
2. Add them to `.env` file (see `.env.example` for format)
3. Run `python3 check_broker_status.py` to verify connection
4. Restart the bot

Required environment variables for each broker:

### Coinbase
```bash
COINBASE_JWT_PEM="..."
COINBASE_JWT_KID="..."
COINBASE_JWT_ISSUER="..."
# OR
COINBASE_API_KEY="..."
COINBASE_API_SECRET="..."
```

### Kraken
```bash
KRAKEN_API_KEY="..."
KRAKEN_API_SECRET="..."
```

### OKX
```bash
OKX_API_KEY="..."
OKX_API_SECRET="..."
OKX_PASSPHRASE="..."
```

### Binance
```bash
BINANCE_API_KEY="..."
BINANCE_API_SECRET="..."
```

### Alpaca
```bash
ALPACA_API_KEY="..."
ALPACA_API_SECRET="..."
```

## More Information

- **Full Setup Guide**: `BROKER_INTEGRATION_GUIDE.md`
- **Multi-Broker Overview**: `MULTI_BROKER_STATUS.md`
- **Trading Strategy**: `bot/trading_strategy.py` (lines 117-260)

## Troubleshooting

If no brokers connect:
1. Check `.env` file exists and has credentials
2. Verify API keys have required permissions (read + trade)
3. Check the error messages in the status report
4. Review broker-specific documentation

If a specific broker fails:
- **Coinbase**: Check JWT format or API key/secret format
- **Kraken/OKX**: Verify API permissions include trading
- **Binance**: Check if testnet flag is set correctly
- **Alpaca**: Verify paper vs live trading credentials

---

**Last Updated**: 2025-12-30
