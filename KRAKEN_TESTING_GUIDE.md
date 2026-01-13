# Kraken Connection Testing Guide

## Overview

This guide explains how to test Kraken connections locally before deploying to production (Railway/Render).

## Test Script: `test_kraken_connection_live.py`

This script tests connections to all configured Kraken accounts (Master, Daivon, Tania) and provides detailed diagnostics.

### Features

- ✅ Tests all configured Kraken accounts
- ✅ Loads credentials from `.env` file (local) or environment variables (deployment)
- ✅ Provides detailed error messages and troubleshooting guidance
- ✅ Shows account balances on successful connection
- ✅ Masks credentials in output for security

---

## Local Testing Setup

### 1. Create `.env` File

The `.env` file stores your Kraken API credentials locally. **This file is NOT committed to git** (it's in `.gitignore`).

Copy the example and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and add your Kraken credentials:

```bash
# KRAKEN EXCHANGE - Master Account
KRAKEN_MASTER_API_KEY=your-master-api-key
KRAKEN_MASTER_API_SECRET=your-master-api-secret

# KRAKEN EXCHANGE - User Accounts
KRAKEN_USER_DAIVON_API_KEY=your-daivon-api-key
KRAKEN_USER_DAIVON_API_SECRET=your-daivon-api-secret

KRAKEN_USER_TANIA_API_KEY=your-tania-api-key
KRAKEN_USER_TANIA_API_SECRET=your-tania-api-secret
```

### 2. Install Dependencies

The test script requires `python-dotenv` and Kraken SDK:

```bash
pip install python-dotenv krakenex pykrakenapi
```

These are already in `requirements.txt`, so if you've run `pip install -r requirements.txt`, you should have them.

### 3. Run the Test

```bash
python3 test_kraken_connection_live.py
```

---

## Understanding Test Results

### ✅ Successful Connection

```
✅ Successfully connected to Kraken!

📊 Account Balance:
  USD (ZUSD): $1234.56
  USDT: $0.00
  Total: $1234.56
```

This means:
- ✅ API credentials are valid
- ✅ API key has required permissions
- ✅ Account is ready for trading

### ❌ Permission Error

```
❌ Kraken API error: EPermission:Invalid key

⚠️  PERMISSION ERROR
Your API key exists but lacks required permissions.
```

**Fix:**
1. Go to https://www.kraken.com/u/security/api
2. Edit your API key permissions
3. Enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Save and re-run the test

### ❌ Authentication Error

```
❌ Kraken API error: EAPI:Invalid key

⚠️  AUTHENTICATION ERROR
Your API key or secret is invalid.
```

**Fix:**
1. Verify credentials at https://www.kraken.com/u/security/api
2. Create a new API key if needed
3. Update `.env` with correct credentials
4. Re-run the test

### ❌ Nonce Error

```
❌ Kraken API error: EAPI:Invalid nonce
```

**Causes:**
- Multiple bots using the same API key
- System clock out of sync
- Concurrent requests

**Fix:**
- Wait a few seconds and try again
- Ensure only one bot uses each API key
- Check system time is correct

---

## Deployment Testing (Railway/Render)

When running on Railway or Render, the script automatically uses environment variables instead of the `.env` file.

### Set Environment Variables

**Railway:**
1. Go to your project → Variables
2. Add each credential:
   - `KRAKEN_MASTER_API_KEY`
   - `KRAKEN_MASTER_API_SECRET`
   - `KRAKEN_USER_DAIVON_API_KEY`
   - `KRAKEN_USER_DAIVON_API_SECRET`
   - `KRAKEN_USER_TANIA_API_KEY`
   - `KRAKEN_USER_TANIA_API_SECRET`
3. Redeploy

**Render:**
1. Go to your service → Environment
2. Add each credential as above
3. Save and redeploy

### Run Test on Deployment

SSH into your deployment and run:

```bash
python3 test_kraken_connection_live.py
```

Or add it as a one-time command in Railway/Render dashboard.

---

## Security Best Practices

### ✅ DO:
- Store credentials in `.env` file locally
- Use environment variables on deployment platforms
- Keep `.env` out of git (it's in `.gitignore`)
- Use separate API keys for each account
- Limit API key permissions to only what's needed

### ❌ DON'T:
- Commit `.env` file to git
- Share API keys in chat/email
- Use the same API key on multiple bots
- Give API keys withdrawal permissions (not needed for trading)
- Store credentials in code files

---

## Troubleshooting

### Test says "No credentials found"

**Check:**
1. `.env` file exists in project root
2. Credentials are not empty in `.env`
3. No extra spaces or quotes around values
4. Variable names exactly match (case-sensitive)

### Test fails with "No module named 'krakenex'"

**Fix:**
```bash
pip install krakenex pykrakenapi
```

### Test fails with "No module named 'dotenv'"

**Fix:**
```bash
pip install python-dotenv
```

### Connection works locally but not on Railway/Render

**Check:**
1. Environment variables are set in platform dashboard
2. Variable names exactly match local `.env`
3. No trailing spaces in variable values
4. Deployment has been restarted after adding variables

---

## Next Steps After Testing

Once all tests pass:

1. **Enable Kraken in config** (if not already enabled)
2. **Restart the bot** to start trading
3. **Monitor logs** for trading activity
4. **Check positions** after 30-60 minutes

See `KRAKEN_QUICK_START.md` for full setup instructions.

---

## Support

If tests continue to fail:

1. Run diagnostic script: `python3 diagnose_kraken_connection.py`
2. Check Kraken API status: https://status.kraken.com/
3. Verify API key at: https://www.kraken.com/u/security/api
4. Review logs for detailed error messages

---

## Summary

```bash
# Quick test workflow:
1. Create .env with credentials
2. pip install python-dotenv krakenex pykrakenapi
3. python3 test_kraken_connection_live.py
4. Fix any errors shown
5. Deploy to Railway/Render with environment variables
```

That's it! The test script makes it easy to verify Kraken connections work before going live.
