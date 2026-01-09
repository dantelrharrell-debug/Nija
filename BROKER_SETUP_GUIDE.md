# NIJA Multi-Broker Setup Guide

## Overview

NIJA supports trading across **5 different brokerages simultaneously**:

1. **Coinbase Advanced Trade** (Crypto - Primary)
2. **Kraken Pro** (Crypto)
3. **OKX** (Crypto + Futures)
4. **Binance** (Crypto)
5. **Alpaca** (Stocks - Paper Trading)

Each broker operates independently, so issues with one broker won't affect trading on others.

---

## Broker Status Check

To check which brokers are currently configured and connected, run:

```bash
python3 check_broker_status.py
```

---

## Quick Start: Minimum Configuration

**To get NIJA trading immediately**, you only need **ONE** broker configured:

### Coinbase (Recommended - Simplest Setup)

Coinbase is the primary broker and is already configured in your `.env` file.

✅ **Status**: Already configured and working!

No additional setup needed for Coinbase.

---

## Adding Additional Brokers (Optional)

### 1. Kraken Pro

**Status**: ✅ Configured for both MASTER and USER accounts

Your Kraken credentials are already set up:
- **MASTER Account**: For Nija system trading
- **USER Account** (Daivon): For user-specific trading

**No action needed** - Kraken is ready to use.

**To verify Kraken connection**:
```bash
python3 check_kraken_connection_status.py
```

---

### 2. OKX Exchange

**Status**: ⚠️ **REQUIRES PASSPHRASE**

Your OKX credentials are partially configured, but **OKX_PASSPHRASE is missing**.

#### How to Fix:

1. Go to [OKX API Management](https://www.okx.com/account/my-api)
2. Find your API key: `ed7a437f-4be0-45c4-b7ee-324c73345292`
3. Locate the **passphrase** you created when generating the API key
4. Edit `.env` file and update line 32:
   ```bash
   OKX_PASSPHRASE=YOUR_ACTUAL_PASSPHRASE_HERE
   ```

**⚠️ SECURITY NOTE**: 
- Your OKX passphrase is NOT the same as your OKX login password
- It's a custom passphrase you created when generating the API key
- Keep it secret and never share it

**Required Permissions**:
- ✅ Trade
- ❌ Withdraw (Do NOT enable for security)

---

### 3. Binance

**Status**: ❌ **NOT CONFIGURED**

Binance credentials are currently missing from your `.env` file.

#### How to Set Up Binance:

1. **Create API Keys**:
   - Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
   - Create a new API key
   - **Enable**: Reading, Spot & Margin Trading
   - **Disable**: Withdrawals (for security)

2. **Add to `.env` file**:
   ```bash
   BINANCE_API_KEY=your_binance_api_key_here
   BINANCE_API_SECRET=your_binance_api_secret_here
   BINANCE_USE_TESTNET=false
   ```

3. **IP Whitelist (Recommended)**:
   - Add your server IP to the API key whitelist for extra security

---

### 4. Alpaca (Stocks - Paper Trading)

**Status**: ✅ Configured with **public paper trading credentials**

Alpaca is set up for **paper trading only** with public test credentials.

**Current Setup**:
```bash
ALPACA_API_KEY=PKS2NORMEX6BMN6P3T63C7ICZ2
ALPACA_API_SECRET=GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ
ALPACA_PAPER=true
```

#### To Enable Live Stock Trading:

1. Sign up at [Alpaca](https://alpaca.markets/)
2. Get your **live trading** API credentials
3. Update `.env`:
   ```bash
   ALPACA_API_KEY=your_live_alpaca_key
   ALPACA_API_SECRET=your_live_alpaca_secret
   ALPACA_PAPER=false
   ```

---

## Primary Broker Selection

NIJA automatically selects a **primary broker** with the following priority:

1. **Coinbase** (if connected)
2. **Kraken** (if Coinbase not available)
3. **OKX** (if Coinbase and Kraken not available)
4. **Binance** (if others not available)
5. **Alpaca** (stocks only, lowest priority)

The primary broker is used for:
- Main trading operations
- Position management
- Balance checks

**You can verify the primary broker** by checking the logs when NIJA starts:
```
📌 PRIMARY BROKER SET: coinbase
```

---

## Multi-Account Trading (User Accounts)

NIJA supports **separate trading for multiple users/investors**.

### Current Setup:

- **MASTER Account**: Nija system trading (uses MASTER credentials)
- **USER #1 (Daivon)**: User-specific trading (uses USER_DAIVON credentials)

### How It Works:

1. **Master Account**:
   - Trades with Nija's capital
   - Uses: `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`

2. **User Accounts**:
   - Each user trades with their own capital
   - Completely isolated from master account
   - User "Daivon" uses: `KRAKEN_USER_DAIVON_API_KEY` and `KRAKEN_USER_DAIVON_API_SECRET`

### Adding More Users:

To add another user account (e.g., "John"):

1. Create Kraken API credentials for the new user
2. Add to `.env`:
   ```bash
   KRAKEN_USER_JOHN_API_KEY=user_john_api_key_here
   KRAKEN_USER_JOHN_API_SECRET=user_john_api_secret_here
   ```

---

## Testing Broker Connections

### Test All Brokers:
```bash
python3 check_broker_status.py
```

### Test Specific Brokers:
```bash
# Kraken
python3 check_kraken_connection_status.py

# OKX
python3 test_okx_connection.py

# Independent broker status
python3 check_independent_broker_status.py
```

---

## Troubleshooting

### Issue: "OKX connection failed"

**Cause**: Missing `OKX_PASSPHRASE` in `.env`

**Solution**: 
1. Find your OKX API passphrase (from when you created the API key)
2. Add it to `.env`: `OKX_PASSPHRASE=your_passphrase`
3. Restart NIJA

---

### Issue: "Kraken connection failed"

**Possible Causes**:
1. API key permissions insufficient
2. API key rate limited (temporary)
3. Invalid credentials

**Solutions**:
- Verify API key has required permissions (Query Funds, Query/Create/Modify/Cancel Orders)
- Wait 30-60 seconds and try again (rate limit cooldown)
- Double-check credentials are copied correctly (no extra spaces)

---

### Issue: "No primary broker available"

**Cause**: No brokers successfully connected

**Solution**:
1. Check that at least ONE broker has valid credentials
2. Run `check_broker_status.py` to see connection errors
3. Fix credentials for at least one broker
4. Restart NIJA

---

## Summary: What You Need to Do

### Immediate Action Required:

1. **OKX Passphrase** (if you want to trade on OKX):
   - Edit `.env` line 32: `OKX_PASSPHRASE=YOUR_ACTUAL_PASSPHRASE`
   - Restart NIJA

### Optional (to enable more brokers):

2. **Binance** (if you want to trade on Binance):
   - Get API credentials from Binance
   - Add `BINANCE_API_KEY` and `BINANCE_API_SECRET` to `.env`

3. **Alpaca Live Trading** (if you want live stock trading):
   - Get live API credentials from Alpaca
   - Update Alpaca credentials in `.env`
   - Set `ALPACA_PAPER=false`

### Already Working:

✅ **Coinbase** - Primary broker, fully configured
✅ **Kraken** - Configured for both MASTER and USER accounts
✅ **Alpaca** - Paper trading ready

---

## Next Steps

Once you've configured your desired brokers:

1. **Restart NIJA**:
   ```bash
   ./start.sh
   ```

2. **Verify connections** in the startup logs:
   ```
   ✅ CONNECTED BROKERS: Coinbase, Kraken, OKX
   📌 PRIMARY BROKER SET: coinbase
   💰 TOTAL BALANCE ACROSS ALL BROKERS: $X,XXX.XX
   ```

3. **Start trading**! NIJA will automatically trade on all connected brokers.

---

## Support

For issues or questions:
- Check logs: `tail -f nija.log`
- Run diagnostics: `python3 check_broker_status.py`
- Review documentation in the repository
