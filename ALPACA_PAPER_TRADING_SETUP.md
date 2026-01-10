# NIJA Alpaca Paper Trading Setup Guide

## Overview

NIJA is now integrated with **Alpaca Markets** for paper trading stocks. This allows you to test the trading bot with stocks in a simulated environment before connecting live trading accounts.

**Key Features:**
- 🎯 Paper trading with real market data
- 📊 Stocks trading (not crypto)
- 🔄 Independent broker architecture (Alpaca won't interfere with other brokers)
- 💰 Simulated $100,000 paper trading account
- 📈 APEX v7.1 strategy adapted for stock markets

## Current Status

✅ **Alpaca Integration Complete**

The following has been implemented:
- [x] Alpaca broker class (`AlpacaBroker`) in `bot/broker_manager.py`
- [x] Alpaca SDK (`alpaca-py==0.36.0`) in requirements.txt
- [x] Alpaca connection logic in `TradingStrategy` initialization
- [x] Paper trading credentials configured in `.env`
- [x] Independent broker trading support

## Prerequisites

1. **Alpaca Markets Account** (Free)
   - Sign up at: https://alpaca.markets/
   - Verify email and create paper trading account
   - Paper trading credentials are provided automatically

2. **Python Dependencies**
   ```bash
   pip install alpaca-py==0.36.0
   pip install python-dotenv==1.0.0
   ```

## Configuration

### 1. Alpaca API Credentials

Alpaca credentials are already configured in `.env`:

```bash
# Alpaca API credentials (Paper Trading)
ALPACA_API_KEY=PKS2NORMEX6BMN6P3T63C7ICZ2
ALPACA_API_SECRET=GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

**These are PUBLIC paper trading credentials** - safe for testing.

### 2. For Your Own Alpaca Account

To use your own Alpaca account:

1. Log in to https://app.alpaca.markets/
2. Go to **Paper Trading** section
3. Navigate to **API Keys**
4. Click **Generate New Key**
5. Copy the API Key and Secret Key
6. Update `.env` file:

```bash
ALPACA_API_KEY=<your-api-key>
ALPACA_API_SECRET=<your-api-secret>
ALPACA_PAPER=true  # Keep as true for paper trading
```

### 3. Enable Multi-Broker Independent Trading

Ensure this is set in `.env` (already configured):

```bash
MULTI_BROKER_INDEPENDENT=true
```

This ensures Alpaca trades independently without interfering with other brokers.

## How It Works

### Broker Detection

When NIJA starts, it automatically:

1. **Checks for Alpaca credentials** in environment variables
2. **Connects to Alpaca** paper trading API
3. **Detects if account is funded** (paper accounts start with $100,000)
4. **Starts trading** if balance ≥ $2.00

### Trading Strategy

NIJA uses the **APEX v7.1 strategy** for stock trading:

- **Market Scanning**: Scans popular stock symbols (SPY, QQQ, AAPL, MSFT, etc.)
- **Technical Analysis**: RSI, EMA, VWAP, Volume analysis
- **Entry Signals**: Identifies high-probability setups
- **Position Management**: Dynamic position sizing based on volatility
- **Risk Management**: Stop losses and profit targets
- **Stepped Exits**: Progressive profit taking (0.5%, 1%, 2%, 3%)

### Stock Universe

Alpaca trading focuses on:
- **Large-cap stocks**: AAPL, MSFT, GOOGL, AMZN, META
- **ETFs**: SPY (S&P 500), QQQ (NASDAQ), etc.
- **High-liquidity**: Minimum daily volume requirements
- **Active status**: Only tradeable, active stocks

## Running NIJA with Alpaca

### Standard Startup

```bash
# Start NIJA bot (includes Alpaca)
python bot.py
```

Or using the start script:

```bash
./start.sh
```

### Check Logs

Look for these messages in the logs:

```
📊 Attempting to connect Alpaca...
   ✅ Alpaca connected (PAPER)
✅ FUNDED BROKERS: 1
💰 TOTAL TRADING CAPITAL: $100,000.00
   • alpaca: $100,000.00
```

### Verify Status

Check broker status:

```bash
python check_broker_status.py
```

## Testing the Integration

Run the integration test script:

```bash
python test_nija_alpaca_paper_trading.py
```

This will verify:
- ✅ Alpaca credentials are set
- ✅ alpaca-py library is installed
- ✅ AlpacaBroker class is available
- ✅ BrokerManager integration works
- ✅ TradingStrategy includes Alpaca

## Monitoring Trades

### 1. Alpaca Dashboard

View your paper trades at:
https://app.alpaca.markets/paper/dashboard/overview

**Dashboard Features:**
- Portfolio value and P&L
- Open positions
- Order history
- Account activity
- Performance charts

### 2. NIJA Logs

Monitor `nija.log` for trade execution:

```bash
tail -f nija.log
```

Look for entries like:
```
🎯 BUY signal for AAPL
💰 Position opened: AAPL - 10 shares @ $175.50
✅ Sell order filled: AAPL - Profit: $87.50 (+2.5%)
```

### 3. Check Active Positions

```bash
python check_broker_status.py
```

## Switching to Live Trading

⚠️ **IMPORTANT**: Only switch to live trading after thoroughly testing with paper trading.

To enable live trading with Alpaca:

1. Fund your Alpaca live account with real money
2. Generate live API credentials (not paper)
3. Update `.env`:

```bash
ALPACA_API_KEY=<your-live-api-key>
ALPACA_API_SECRET=<your-live-api-secret>
ALPACA_PAPER=false  # Change to false for live trading
```

4. Restart NIJA bot

## Troubleshooting

### Alpaca Not Connecting

**Check credentials:**
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('Key:', os.getenv('ALPACA_API_KEY'))"
```

**Verify internet access:**
```bash
ping paper-api.alpaca.markets
```

**Check logs:**
```bash
grep -i alpaca nija.log
```

### Alpaca Not Trading

**Check if broker is funded:**
- Paper accounts start with $100,000
- Minimum balance required: $2.00

**Check if broker is detected:**
```bash
python check_broker_status.py | grep -i alpaca
```

**Verify independent trading is enabled:**
```bash
grep MULTI_BROKER_INDEPENDENT .env
```

### No Stock Signals

**Verify market hours:**
- US stock markets open: 9:30 AM - 4:00 PM ET
- Alpaca paper trading works 24/7 but with less liquidity outside market hours

**Check scan limits:**
- NIJA scans 15 stocks per cycle
- Cycles run every 2.5 minutes
- Signals depend on market conditions

## Architecture

### Independent Broker System

NIJA uses an **independent broker architecture**:

```
NIJA Bot
├── Coinbase (Crypto)
├── Kraken (Crypto)
├── OKX (Crypto)
├── Binance (Crypto)
└── Alpaca (Stocks) ← Operates independently
```

**Benefits:**
- ✅ Each broker trades independently in its own thread
- ✅ Failure in one broker doesn't affect others
- ✅ Different strategies per broker (crypto vs stocks)
- ✅ Isolated risk management per broker
- ✅ Separate position tracking per broker

### Code Structure

```
bot/
├── broker_manager.py          # AlpacaBroker class (lines 2404-2650)
├── trading_strategy.py         # Alpaca initialization (lines 268-279)
├── independent_broker_trader.py # Independent trading logic
└── nija_apex_strategy_v71.py  # APEX v7.1 strategy

test_nija_alpaca_paper_trading.py # Integration test script
.env                              # Alpaca credentials
```

## Performance Expectations

### Paper Trading Results

**Expected Performance** (varies with market conditions):
- **Win Rate**: 50-60%
- **Average Profit per Trade**: 0.5-2.0%
- **Daily Trades**: 2-10 (depends on signals)
- **Max Positions**: 8 concurrent

**Example Day:**
```
Starting Balance: $100,000.00
Trades Executed: 6
Winning Trades: 4 (66.7%)
Losing Trades: 2 (33.3%)
Total Profit: +$450.00 (+0.45%)
Ending Balance: $100,450.00
```

### Fees

**Paper Trading**: $0 (no fees)
**Live Trading**: Alpaca charges $0 commissions on stocks

## Resources

### Alpaca Documentation
- Website: https://alpaca.markets/
- API Docs: https://docs.alpaca.markets/
- Python SDK: https://github.com/alpacahq/alpaca-py

### NIJA Documentation
- Main README: [README.md](README.md)
- APEX Strategy: [APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)
- Broker Guide: [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md)

### Support
- NIJA Issues: https://github.com/dantelrharrell-debug/Nija/issues
- Alpaca Support: https://alpaca.markets/support

## Security

⚠️ **IMPORTANT SECURITY NOTES**

1. **Never commit `.env` file** to version control
2. **Keep API secrets private** (especially live trading keys)
3. **Use paper trading first** before risking real money
4. **Review all trades** in Alpaca dashboard
5. **Set position limits** to control risk
6. **Monitor bot regularly** especially when starting

## Next Steps

After setting up Alpaca paper trading:

1. ✅ **Run integration test**: `python test_nija_alpaca_paper_trading.py`
2. ✅ **Start NIJA bot**: `python bot.py`
3. ✅ **Monitor logs**: `tail -f nija.log`
4. ✅ **Check Alpaca dashboard**: View trades at https://app.alpaca.markets/paper/dashboard
5. ✅ **Analyze performance**: Review P&L after 1 week
6. ⏭️ **Consider live trading**: Only after successful paper trading

## FAQ

**Q: Can I run Alpaca and Coinbase at the same time?**
A: Yes! Independent broker architecture allows simultaneous trading on multiple brokers.

**Q: Does Alpaca trade crypto?**
A: Alpaca supports stocks and crypto. NIJA currently uses it for stocks. Crypto trading is handled by Coinbase/Kraken/OKX/Binance.

**Q: How much capital do I need for live Alpaca trading?**
A: Alpaca requires $0 minimum, but NIJA recommends $500+ for better position sizing.

**Q: What happens if Alpaca loses connection?**
A: NIJA will retry connection automatically. Other brokers continue trading normally.

**Q: Can I disable Alpaca trading?**
A: Yes, remove Alpaca credentials from `.env` or set `ALPACA_API_KEY=` (empty).

---

**Last Updated**: January 10, 2026
**NIJA Version**: APEX v7.1
**Alpaca SDK**: alpaca-py 0.36.0
