# NIJA Environment Variables Configuration Guide

**Last Updated**: January 10, 2026  
**Purpose**: Complete guide for configuring environment variables for local development and deployment

---

## Overview

NIJA requires environment variables for:
1. **Broker API Credentials** (Coinbase, Kraken, OKX, Binance, Alpaca)
2. **Multi-Account Support** (MASTER account + USER accounts)
3. **Bot Configuration** (live trading, risk parameters)

---

## Local Development (.env file)

For local development, copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Then edit `.env` with your actual API keys.

⚠️ **IMPORTANT**: Never commit your `.env` file to Git! It's in `.gitignore` for security.

---

## Production Deployment (Railway/Render/etc.)

For production deployments, **environment variables must be set in your hosting platform**, not in `.env` file.

### Why?

- The `.env` file is not included in Docker deployments for security
- Environment variables must be configured in Railway/Render/Heroku dashboard
- This prevents accidentally committing sensitive credentials to Git

---

## Required Environment Variables

### 🔵 Coinbase Advanced Trade (Primary Broker)

```bash
COINBASE_ORG_ID=your-org-id
COINBASE_JWT_PEM="-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY\n-----END EC PRIVATE KEY-----"
COINBASE_JWT_KID=your-key-id
COINBASE_JWT_ISSUER=organizations/your-org-id
```

**How to get**: https://portal.cloud.coinbase.com/access/api

**Notes**:
- For Railway/Render: The PEM key must be on ONE line with `\n` escape sequences (not actual newlines)
- Required for NIJA to trade

---

### 🟢 Kraken Pro (Multi-Account Support)

NIJA supports **two types of Kraken accounts**:

#### 1. MASTER Account (Nija System Account)

```bash
KRAKEN_MASTER_API_KEY=your_master_api_key
KRAKEN_MASTER_API_SECRET=your_master_api_secret
```

#### 2. USER Accounts (Individual Investors)

Format: `KRAKEN_USER_{FIRSTNAME}_API_KEY`

**Example for user "daivon_frazier"**:

```bash
KRAKEN_USER_DAIVON_API_KEY=your_user_api_key
KRAKEN_USER_DAIVON_API_SECRET=your_user_api_secret
```

**How it works**:
- User ID: `daivon_frazier`
- First name extracted: `DAIVON`
- Environment variables: `KRAKEN_USER_DAIVON_API_KEY` / `KRAKEN_USER_DAIVON_API_SECRET`

**For another user "john_smith"**:

```bash
KRAKEN_USER_JOHN_API_KEY=your_user_api_key
KRAKEN_USER_JOHN_API_SECRET=your_user_api_secret
```

**⚠️ CRITICAL FOR DEPLOYMENT**:

If you see this error in logs:
```
❌ USER #1 (Daivon Frazier): NOT TRADING (Connection failed or not configured)
```

This means `KRAKEN_USER_DAIVON_API_KEY` and `KRAKEN_USER_DAIVON_API_SECRET` are **not set in your deployment platform**.

**How to fix**:
1. Log into Railway/Render dashboard
2. Navigate to your NIJA service
3. Go to "Variables" or "Environment" section
4. Add both variables with your actual Kraken API credentials
5. Redeploy the service

**How to get Kraken API keys**: https://www.kraken.com/u/security/api

**Required Permissions**:
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ❌ Withdraw Funds (Do NOT enable for security)

---

### 🟠 OKX Exchange (Optional)

```bash
OKX_API_KEY=your_api_key
OKX_API_SECRET=your_api_secret
OKX_PASSPHRASE=your_passphrase
OKX_USE_TESTNET=false
```

**How to get**: https://www.okx.com/account/my-api

**Notes**:
- OKX requires a passphrase (set when creating API key)
- Passphrase is NOT your OKX login password
- Keep passphrase secure

---

### 🟡 Binance (Optional)

```bash
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_USE_TESTNET=false
```

**How to get**: https://www.binance.com/en/my/settings/api-management

---

### 🔴 Alpaca (Stock Trading - Optional)

```bash
ALPACA_API_KEY=your_api_key
ALPACA_API_SECRET=your_api_secret
ALPACA_PAPER=true  # Set to false for live trading
```

**How to get**: https://alpaca.markets/

**For paper trading** (testing):
```bash
ALPACA_API_KEY=PKS2NORMEX6BMN6P3T63C7ICZ2
ALPACA_API_SECRET=GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ
ALPACA_PAPER=true
```

---

## Bot Configuration Variables

```bash
# Enable live trading (set to 1 for real trades, 0 for paper trading)
LIVE_TRADING=1

# Include consumer/retail USD accounts in balance calculation
ALLOW_CONSUMER_USD=true

# Multi-broker independent trading (each broker runs isolated)
MULTI_BROKER_INDEPENDENT=true

# Risk parameters (optional - bot has defaults)
MIN_TRADE_PERCENT=0.02
MAX_TRADE_PERCENT=0.10
DEFAULT_TRADE_PERCENT=0.05
RETRY_DELAY=5
MAX_RETRIES=5
```

---

## Platform-Specific Guides

### Railway Deployment

1. **Go to Railway Dashboard**: https://railway.app/dashboard
2. **Select your NIJA project**
3. **Click on the service**
4. **Go to "Variables" tab**
5. **Click "New Variable"**
6. **Add each variable**:
   - Variable name: `KRAKEN_USER_DAIVON_API_KEY`
   - Variable value: `your_actual_api_key`
   - Click "Add"
7. **Repeat for all required variables**
8. **Redeploy** (Railway auto-redeploys on variable changes)

**Important**: For `COINBASE_JWT_PEM`, the value must be ONE line with `\n` escape sequences:
```
-----BEGIN EC PRIVATE KEY-----\nMHcCAQ...\n-----END EC PRIVATE KEY-----\n
```

### Render Deployment

1. **Go to Render Dashboard**: https://dashboard.render.com/
2. **Select your NIJA service**
3. **Go to "Environment" tab**
4. **Click "Add Environment Variable"**
5. **Add each variable** and click "Save Changes"
6. **Manually redeploy** (Render doesn't auto-redeploy on variable changes)

### Heroku Deployment

```bash
# Using Heroku CLI
heroku config:set KRAKEN_USER_DAIVON_API_KEY=your_api_key
heroku config:set KRAKEN_USER_DAIVON_API_SECRET=your_api_secret
heroku config:set LIVE_TRADING=1
```

Or use Heroku Dashboard:
1. **Go to app settings**
2. **Click "Reveal Config Vars"**
3. **Add each variable**

---

## Verification

### Local Development

```bash
python3 verify_kraken_credentials_simple.py
```

Expected output:
```
✅ KRAKEN CREDENTIALS VERIFIED

MASTER Account (Nija System):
  ✅ KRAKEN_MASTER_API_KEY: Set (56 chars)
  ✅ KRAKEN_MASTER_API_SECRET: Set (88 chars)

USER Account (Daivon):
  ✅ KRAKEN_USER_DAIVON_API_KEY: Set (56 chars)
  ✅ KRAKEN_USER_DAIVON_API_SECRET: Set (88 chars)
```

### Production Deployment

Check your deployment logs for:

**✅ Success**:
```
📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $XXX.XX
✅ USER #1 (Daivon Frazier): TRADING (Broker: Kraken)
```

**❌ Failure** (missing credentials):
```
⚠️ Kraken credentials not configured for USER:daivon_frazier (skipping)
   ⚠️ User #1 Kraken connection failed
❌ USER #1 (Daivon Frazier): NOT TRADING (Connection failed or not configured)
```

If you see the failure message, the environment variables are not set in your deployment platform.

---

## Troubleshooting

### Issue: "NOT TRADING (Connection failed or not configured)"

**Cause**: Environment variables not set in deployment platform

**Solution**:
1. Verify variables are set in Railway/Render dashboard (not just in `.env` file)
2. Check variable names match exactly (case-sensitive)
3. Ensure no extra spaces in variable values
4. Redeploy after adding variables

### Issue: "Kraken credentials not configured"

**Cause**: Variable names don't match expected format

**Solution**:
- For user "daivon_frazier", use `KRAKEN_USER_DAIVON_API_KEY` (first name in UPPERCASE)
- For user "john", use `KRAKEN_USER_JOHN_API_KEY`
- Check the code extracts first name: `user_id.split('_')[0].upper()`

### Issue: "EGeneral:Permission denied" or "Kraken connection test failed: Permission denied"

**Cause**: Your Kraken API key exists but doesn't have sufficient permissions

**Solution**:
1. Go to https://www.kraken.com/u/security/api
2. Find your API key and click "Edit" or "Manage"
3. Enable these permissions:
   - ✅ **Query Funds** (required to check balance)
   - ✅ **Query Open Orders & Trades** (required for position tracking)
   - ✅ **Query Closed Orders & Trades** (required for trade history)
   - ✅ **Create & Modify Orders** (required to place trades)
   - ✅ **Cancel/Close Orders** (required for stop losses)
   - ❌ **Withdraw Funds** (DO NOT enable for security)
4. Save changes
5. Restart the bot (redeploy if in production)

**Note**: The bot needs at minimum "Query Funds" permission to connect. Without it, you'll get "Permission denied" errors even though your API key is valid.

### Issue: Coinbase PEM key not working in Railway

**Cause**: Newlines in PEM key

**Solution**:
- PEM key must be ONE line with `\n` escape sequences
- Wrong: Multi-line value with actual newlines
- Right: `-----BEGIN EC PRIVATE KEY-----\nMHc...\n-----END EC PRIVATE KEY-----\n`

---

## Security Best Practices

1. ✅ **Never commit credentials to Git**
   - `.env` is in `.gitignore`
   - Never hardcode API keys in code

2. ✅ **Use read-only or limited permissions**
   - Enable trading permissions only
   - Never enable withdrawal permissions on exchange APIs

3. ✅ **Rotate API keys regularly**
   - Change keys every 3-6 months
   - Immediately rotate if exposed

4. ✅ **Use separate keys for different environments**
   - Development: Use testnet/paper trading keys
   - Production: Use live trading keys with limited balance

5. ✅ **Monitor API key usage**
   - Check exchange dashboards for unauthorized access
   - Set up IP whitelisting when possible

---

## Minimal Configuration

**To get NIJA running with minimum setup**, you only need:

```bash
# Coinbase (required)
COINBASE_ORG_ID=...
COINBASE_JWT_PEM=...
COINBASE_JWT_KID=...
COINBASE_JWT_ISSUER=...

# Enable live trading
LIVE_TRADING=1
ALLOW_CONSUMER_USD=true
```

All other brokers (Kraken, OKX, Binance, Alpaca) are optional.

---

## Full Configuration Example

See `.env.example` file for a complete template with all available options.

---

## Questions or Issues?

1. Check deployment logs for specific error messages
2. Review this guide for the variable you're trying to set
3. Verify variable names match exactly (case-sensitive)
4. Ensure values have no extra spaces or quotes (unless required)
5. Check platform-specific documentation (Railway/Render/Heroku)

---

**Last Updated**: January 10, 2026  
**Related Documentation**:
- `BROKER_SETUP_GUIDE.md` - Detailed broker setup instructions
- `RAILWAY_DEPLOYMENT_FIX.md` - Railway-specific deployment issues
- `MASTER_USER_ACCOUNT_SEPARATION_GUIDE.md` - Multi-account architecture
