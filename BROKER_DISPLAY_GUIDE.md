# Broker Display Guide

## Overview

The `display_broker_status.py` script provides a comprehensive, at-a-glance view of all broker configurations in NIJA. It shows which exchanges are configured, which SDKs are installed, and provides actionable next steps for setup.

## Quick Start

```bash
python3 display_broker_status.py
```

## What It Shows

### 1. SDK Availability
- **Coinbase REST client**: Checks if `coinbase.rest` SDK is installed
- Shows ✅ if available, ❌ if not installed

### 2. Configuration Status
For each supported broker/account, shows:
- ✅ **Configured**: Credentials are set with lengths shown
- ❌ **Not configured**: Credentials are missing

### 3. Supported Brokers

#### Master Accounts (Trading System)
- **Coinbase**: Primary cryptocurrency exchange
- **KRAKEN (Master)**: Cryptocurrency exchange (master account)
- **ALPACA (Master)**: Stock and crypto trading platform
- **OKX (Master)**: Cryptocurrency exchange
- **BINANCE (Master)**: Cryptocurrency exchange

#### User Accounts (Individual Traders)
- **KRAKEN (User #1: Daivon)**: Individual Kraken account
- **KRAKEN (User #2: Tania)**: Individual Kraken account
- **ALPACA (User #2: Tania)**: Individual Alpaca account

### 4. Summary Statistics
- Master accounts configured (out of 5)
- User accounts configured (out of 3)
- Total accounts configured (out of 8)

### 5. Trading Readiness Assessment
- **✅ Ready to trade**: At least one master account is configured
- **❌ Cannot trade**: No accounts configured
- **⚠️ Limited**: Only user accounts or only master accounts

## Example Output

### No Accounts Configured
```
================================================================================
  NIJA BROKER STATUS
================================================================================

   Coinbase:
      ✅ Coinbase REST client available
      ❌ Not configured
   📊 KRAKEN (Master):
      ❌ Not configured
   👤 KRAKEN (User #1: Daivon):
      ❌ Not configured
   👤 KRAKEN (User #2: Tania):
      ❌ Not configured
   📊 ALPACA (Master):
      ❌ Not configured
   👤 ALPACA (User #2: Tania):
      ❌ Not configured
   📊 OKX (Master):
      ❌ Not configured
   📊 BINANCE (Master):
      ❌ Not configured

================================================================================

Summary:
  • Master accounts configured: 0/5
  • User accounts configured: 0/3
  • Total accounts configured: 0/8

❌ No accounts configured - trading cannot begin

Next steps:
  1. Set environment variables for at least one exchange
  2. See .env.example for credential format
  3. Run this script again to verify
```

### Binance Configured
```
================================================================================
  NIJA BROKER STATUS
================================================================================

   Coinbase:
      ✅ Coinbase REST client available
      ❌ Not configured
   📊 KRAKEN (Master):
      ❌ Not configured
   👤 KRAKEN (User #1: Daivon):
      ❌ Not configured
   👤 KRAKEN (User #2: Tania):
      ❌ Not configured
   📊 ALPACA (Master):
      ❌ Not configured
   👤 ALPACA (User #2: Tania):
      ❌ Not configured
   📊 OKX (Master):
      ❌ Not configured
   📊 BINANCE (Master):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)

================================================================================

Summary:
  • Master accounts configured: 1/5
  • User accounts configured: 0/3
  • Total accounts configured: 1/8

✅ Ready to trade!

  Master account will trade on 1 exchange(s)
```

## Environment Variables

The script checks for these environment variables:

### Coinbase
- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`

### Kraken Master
- `KRAKEN_MASTER_API_KEY`
- `KRAKEN_MASTER_API_SECRET`

### Kraken Users
- `KRAKEN_USER_DAIVON_API_KEY`
- `KRAKEN_USER_DAIVON_API_SECRET`
- `KRAKEN_USER_TANIA_API_KEY`
- `KRAKEN_USER_TANIA_API_SECRET`

### Alpaca Master
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `ALPACA_PAPER` (optional, defaults to "true")

### Alpaca Users
- `ALPACA_USER_TANIA_API_KEY`
- `ALPACA_USER_TANIA_API_SECRET`
- `ALPACA_USER_TANIA_PAPER` (optional)

### OKX
- `OKX_API_KEY`
- `OKX_API_SECRET`
- `OKX_PASSPHRASE`

### Binance
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`

## Exit Codes

- **0**: Success - at least one master account is configured
- **1**: Failure - no accounts configured, trading cannot begin

## Use Cases

### 1. Initial Setup Verification
After setting up environment variables, run this script to verify they were loaded correctly.

```bash
# Set environment variables
export BINANCE_API_KEY="your-key"
export BINANCE_API_SECRET="your-secret"

# Verify configuration
python3 display_broker_status.py
```

### 2. Deployment Verification
On Railway, Render, or other platforms after adding credentials:

```bash
# SSH into deployment or check logs
python3 display_broker_status.py
```

### 3. Troubleshooting
If trading isn't working, check broker status to ensure credentials are loaded:

```bash
python3 display_broker_status.py
```

### 4. Multi-Account Setup
When configuring multiple accounts, verify each one as you add it:

```bash
# Add master Kraken credentials
export KRAKEN_MASTER_API_KEY="..."
export KRAKEN_MASTER_API_SECRET="..."

# Verify
python3 display_broker_status.py

# Add user Daivon credentials
export KRAKEN_USER_DAIVON_API_KEY="..."
export KRAKEN_USER_DAIVON_API_SECRET="..."

# Verify again
python3 display_broker_status.py
```

## Integration with Other Tools

This script complements other NIJA diagnostic tools:

- **[validate_all_env_vars.py](validate_all_env_vars.py)**: More detailed validation with colors
- **[verify_multi_exchange_status.py](verify_multi_exchange_status.py)**: Multi-exchange setup verification
- **[check_trading_status.py](check_trading_status.py)**: Overall trading readiness check
- **[diagnose_env_vars.py](diagnose_env_vars.py)**: Environment variable diagnostics

## Tips

1. **Run after any credential changes** to verify they were loaded correctly
2. **Check credential lengths** - they should match expected lengths (typically 56-88 chars for keys/secrets)
3. **Ensure SDK is installed** - Coinbase REST client should show ✅
4. **Start with one exchange** - verify it works before adding more
5. **Use .env.example as reference** for credential format

## Common Issues

### Coinbase REST client NOT installed
**Solution**: Install the SDK
```bash
pip install coinbase-advanced-py==1.8.2
```

### Credentials show 0 chars
**Issue**: Environment variables not set or have only whitespace
**Solution**: Check for typos in variable names, ensure values are not empty

### All show "Not configured"
**Issue**: Environment variables not loaded
**Solutions**:
- Check `.env` file exists and has correct values
- Ensure `python-dotenv` is installed for local development
- On deployment platforms, verify variables are set in the dashboard
- Restart the application after adding variables

## See Also

- [MULTI_EXCHANGE_TRADING_GUIDE.md](MULTI_EXCHANGE_TRADING_GUIDE.md) - Complete multi-exchange setup
- [.env.example](.env.example) - Template for environment variables
- [GETTING_STARTED.md](GETTING_STARTED.md) - Initial setup guide
