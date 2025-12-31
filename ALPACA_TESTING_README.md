# Alpaca Testing Guide

This directory contains test scripts for Alpaca integration with NIJA.

## Test Files

### 1. `test_alpaca_simple.py`
Simple test using the exact code provided with paper trading credentials.

**Usage:**
```bash
# Install required library (NOT in requirements.txt due to dependency conflicts)
pip install alpaca-trade-api==3.2.0 websockets<11.0

# Run test
python test_alpaca_simple.py
```

**What it does:**
- Connects to Alpaca paper trading account
- Displays account information
- Lists current positions

### 2. `test_alpaca_integration.py`
Comprehensive test that checks all three integration methods:

**Usage:**
```bash
# Install required libraries
# Note: alpaca-trade-api NOT in requirements.txt, manual install needed for Method 1
pip install alpaca-trade-api==3.2.0 websockets<11.0
pip install alpaca-py  # Already in requirements.txt

# Run test
python test_alpaca_integration.py
```

**What it tests:**
1. **Method 1:** Old `alpaca_trade_api` library (manual install required)
2. **Method 2:** New `alpaca-py` library (NIJA's current integration)
3. **Method 3:** NIJA's `AlpacaBroker` class

## Paper Trading Credentials

For testing purposes, use these paper trading credentials:

```bash
API_KEY = "PKS2NORMEX6BMN6P3T63C7ICZ2"
API_SECRET = "GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ"
BASE_URL = "https://paper-api.alpaca.markets/v2"
```

These are **paper trading credentials only** - they do not access real money.

## Setting Up Alpaca with NIJA

### Option 1: Add to `.env` file

```bash
# Copy .env.example to .env
cp .env.example .env

# Add Alpaca credentials
ALPACA_API_KEY=PKS2NORMEX6BMN6P3T63C7ICZ2
ALPACA_API_SECRET=GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ
ALPACA_PAPER=true
```

### Option 2: Export as environment variables

```bash
export ALPACA_API_KEY="PKS2NORMEX6BMN6P3T63C7ICZ2"
export ALPACA_API_SECRET="GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ"
export ALPACA_PAPER="true"
```

## Testing NIJA Integration

After setting credentials:

```bash
# Test Alpaca connection
python test_alpaca_integration.py

# Check all broker connections
python check_broker_status.py
```

## Libraries Required

**IMPORTANT:** Due to dependency conflicts with websockets versions, `alpaca-trade-api` has been removed from `requirements.txt`.

### For alpaca-py (newer library, NIJA uses this - IN requirements.txt):
```bash
pip install alpaca-py
```

### For alpaca_trade_api (older library - NOT in requirements.txt):
```bash
# Manual installation required for testing only
pip install alpaca-trade-api==3.2.0 websockets<11.0
```

**Note:** The older `alpaca-trade-api` library requires `websockets<11.0`, which conflicts with other dependencies that require `websockets>=12`. NIJA uses the newer `alpaca-py` library for production, which is compatible with modern websockets versions.

## About Alpaca

- **Alpaca** is a commission-free stock trading API
- Supports stocks, ETFs, and crypto
- Provides paper trading for testing
- API documentation: https://alpaca.markets/docs/

## NIJA Multi-Asset Trading

NIJA is an AI-powered autonomous trading bot that trades:
- **Cryptocurrencies** via OKX, Binance, Coinbase, Kraken
- **Stocks** via Alpaca
- **Futures** (expanding capabilities)

For micro trading:
- **Crypto**: Use OKX (lowest fees, micro perpetuals)
- **Stocks**: Use Alpaca (commission-free)

## Troubleshooting

### ImportError: No module named 'alpaca_trade_api'
```bash
# This library is NOT in requirements.txt due to dependency conflicts
# Manual installation required:
pip install alpaca-trade-api==3.2.0 websockets<11.0
```

### ImportError: No module named 'alpaca'
```bash
# This library IS in requirements.txt
pip install alpaca-py
```

### Connection Failed
- Check API credentials are correct
- Verify you're using paper trading credentials
- Check internet connection
- Verify Alpaca API is not down: https://alpaca.markets/status

### "Account not found" or "Invalid API key"
- Make sure you're using the correct credentials
- Paper trading credentials only work with paper trading mode
- Live credentials only work with live mode

## Getting Your Own Alpaca Credentials

1. Sign up at: https://alpaca.markets/
2. Complete KYC verification (for live trading)
3. Go to: API Keys
4. Create new API key
5. Choose "Paper Trading" or "Live Trading"
6. Save the API Key and Secret Key

**Security Best Practices:**
- Never commit API credentials to version control
- Use `.env` file (already in `.gitignore`)
- Use paper trading for testing
- Restrict API key permissions (trading only, no withdrawals)

## Support

For Alpaca-specific questions:
- Documentation: https://alpaca.markets/docs/
- Support: https://alpaca.markets/support
- Community: https://forum.alpaca.markets/

For NIJA integration questions:
- See `BROKER_INTEGRATION_GUIDE.md`
- See `OKX_MICRO_TRADING_GUIDE.md`
