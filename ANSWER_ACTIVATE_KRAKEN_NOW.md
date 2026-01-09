# ACTIVATING KRAKEN TRADING - BOTH ACCOUNTS

**Date:** January 9, 2026  
**Issue:** Kraken not connected - only Coinbase trading

## 🎯 The Problem

You're seeing:
```
🔄 coinbase - Cycle #1
🔄 coinbase - Cycle #2
```

You should be seeing:
```
🔄 coinbase - Cycle #1
🔄 kraken - Cycle #1
```

**Why?** The bot has Kraken credentials but they're not being loaded properly into the production environment, OR there's an error during Kraken connection that's being silently skipped.

---

## ✅ The Solution

### Quick Fix (Run This Now)

```bash
# Step 1: Verify Kraken credentials and test connection
python3 enable_kraken_and_verify.py

# Step 2: Activate both NIJA's and User #1's Kraken accounts
python3 activate_kraken_trading_both_accounts.py

# Step 3: Restart the bot
# (Railway will automatically pick up environment changes)
```

---

## 📋 What These Scripts Do

### Script 1: `enable_kraken_and_verify.py`
- ✅ Checks if KRAKEN_API_KEY and KRAKEN_API_SECRET are set
- ✅ Tests connection to Kraken Pro API
- ✅ Shows your Kraken account balance
- ✅ Confirms the bot will connect to Kraken on startup

### Script 2: `activate_kraken_trading_both_accounts.py`
- ✅ Verifies Kraken credentials
- ✅ Tests Kraken connection
- ✅ Initializes multi-user system
- ✅ Sets up User #1 (Daivon Frazier) with Kraken
- ✅ Enables User #1 trading
- ✅ Verifies multi-broker configuration

---

## 🔍 Why Kraken Wasn't Connecting

Looking at your logs, the bot shows:
```
2026-01-09 11:39:14 | INFO | ⏱️  Waiting 15s before connecting to avoid rate limits...
```

But you DON'T see:
```
📊 Attempting to connect Kraken Pro...
   ✅ Kraken connected
```

**Possible reasons:**

1. **Environment variables not loaded in production**
   - Kraken credentials in .env file
   - Railway/deployment platform needs them configured

2. **Connection failed silently**
   - The code has `except Exception` that just logs a warning
   - Check bot logs for: `⚠️  Kraken error: ...`

3. **API permissions issue**
   - Kraken API needs: Query Funds, Query/Create/Modify Orders
   - Check your Kraken API key permissions

4. **Rate limiting on startup**
   - If Kraken API was hit recently, connection may fail
   - Bot retries 5 times with exponential backoff

---

## 🚀 Expected Behavior After Fix

When the bot starts, you'll see:

```
2026-01-09 XX:XX:XX | INFO | ⏱️  Waiting 15s before connecting...
2026-01-09 XX:XX:XX | INFO | 📊 Attempting to connect Coinbase...
2026-01-09 XX:XX:XX | INFO |    ✅ Coinbase connected
2026-01-09 XX:XX:XX | INFO | 📊 Attempting to connect Kraken Pro...
2026-01-09 XX:XX:XX | INFO |    ✅ Kraken connected
2026-01-09 XX:XX:XX | INFO | ======================================================================
2026-01-09 XX:XX:XX | INFO | ✅ KRAKEN PRO CONNECTED
2026-01-09 XX:XX:XX | INFO | ======================================================================
2026-01-09 XX:XX:XX | INFO |    USD Balance: $XXX.XX
2026-01-09 XX:XX:XX | INFO |    USDT Balance: $XXX.XX
2026-01-09 XX:XX:XX | INFO |    Total: $XXX.XX
2026-01-09 XX:XX:XX | INFO | ======================================================================
```

Then during trading cycles:
```
2026-01-09 XX:XX:XX | INFO | 🔄 coinbase - Cycle #1
2026-01-09 XX:XX:XX | INFO | 🔄 kraken - Cycle #1
```

---

## 👤 User #1 Status

User #1 (Daivon Frazier) has:
- ✅ Kraken API credentials configured
- ✅ User setup script ready (`setup_user_daivon.py`)
- ❌ Multi-user system NOT initialized (needs activation)

To activate User #1:
```bash
python3 activate_kraken_trading_both_accounts.py
```

This will:
1. Initialize the multi-user system
2. Create User #1's account
3. Store encrypted Kraken credentials
4. Enable trading for User #1

---

## 🔧 Manual Verification

If scripts don't work, manually check:

### 1. Environment Variables
```bash
# Check if set
env | grep KRAKEN

# Should show:
# KRAKEN_API_KEY=8zdYy7PMRjnyDraiJUtr...
# KRAKEN_API_SECRET=e2xaakHliGa5RwH7uXwu...
```

### 2. Kraken SDK Installed
```bash
pip list | grep kraken

# Should show:
# krakenex        2.2.2
# pykrakenapi     0.3.2
```

### 3. Test Connection Directly
```python
import krakenex
from pykrakenapi import KrakenAPI
import os

api = krakenex.API(
    key=os.getenv('KRAKEN_API_KEY'),
    secret=os.getenv('KRAKEN_API_SECRET')
)

balance = api.query_private('Balance')
print(balance)
# Should show your balance, not error
```

---

## 📊 Current Configuration

Your .env file has:
```bash
# Kraken credentials - THESE ARE SET
KRAKEN_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==

# Multi-broker mode - ENABLED
MULTI_BROKER_INDEPENDENT=true
```

The bot code (bot/trading_strategy.py lines 197-208) is configured to:
1. Try to connect Coinbase ✅
2. Try to connect Kraken ✅ (but fails silently if env vars missing)
3. Try to connect OKX
4. Try to connect Binance
5. Try to connect Alpaca

---

## ⚠️ If Kraken Still Won't Connect

Check Railway/deployment platform:

1. **Environment Variables**
   - Go to Railway dashboard
   - Check Variables section
   - Ensure KRAKEN_API_KEY and KRAKEN_API_SECRET are set
   - NOT just in .env file - must be in Railway config

2. **Deployment Logs**
   - Look for "Attempting to connect Kraken"
   - Look for "Kraken error:" messages
   - Share those errors if connection fails

3. **API Key Permissions**
   - Go to Kraken.com → Security → API
   - Verify key has:
     - ✅ Query Funds
     - ✅ Query Orders
     - ✅ Create Orders
     - ✅ Modify Orders
     - ✅ Cancel Orders
   - ❌ DO NOT enable Withdraw (security risk)

---

## 🎯 Summary

**Current Status:**
- ✅ Kraken credentials in .env file
- ✅ Kraken SDK installed
- ✅ Bot code configured for Kraken
- ❌ Kraken not connecting in production

**Action Required:**
1. Run `python3 enable_kraken_and_verify.py`
2. Run `python3 activate_kraken_trading_both_accounts.py`
3. Check Railway environment variables
4. Restart bot and watch logs

**Expected Result:**
- Both Coinbase AND Kraken trading simultaneously
- User #1's Kraken account active (if multi-user enabled)
- Logs showing "kraken - Cycle #X" messages

---

**Files Created:**
- `enable_kraken_and_verify.py` - Test Kraken connection
- `activate_kraken_trading_both_accounts.py` - Full activation script
