# Configure Kraken Master Credentials - Quick Setup Guide

**Last Updated:** January 16, 2026  
**Purpose:** Configure KRAKEN_MASTER credentials to enable Kraken master account trading

---

## Overview

This guide helps you configure the **Kraken Master** account credentials so your bot can trade on Kraken exchange alongside Coinbase.

**Current Status:**
- ✅ Code: Kraken integration fully implemented
- ✅ Libraries: krakenex + pykrakenapi installed
- ⚠️  Configuration: **Credentials need to be added** (you are here)

---

## Quick Setup (5 Minutes)

### Step 1: Get Kraken API Credentials

1. **Log in to Kraken:** https://www.kraken.com
2. **Navigate to API settings:** Settings → Security → API
3. **Click "Add Key" or "Generate New Key"**
4. **Configure permissions** (Required for trading):
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **DO NOT** enable: Withdraw Funds (security risk)
   - ❌ **DO NOT** enable: Deposit Funds (not needed)

5. **Set description:** "NIJA Master Trading Bot"
6. **Click "Generate Key"**
7. **⚠️  IMPORTANT:** Copy BOTH the API Key and Private Key immediately
   - You won't be able to see the Private Key again!
   - API Key: ~56 characters
   - Private Key: ~88 characters (base64 encoded)

8. **Store credentials securely** (password manager recommended)

---

### Step 2: Add Credentials to Your Deployment Platform

Choose the platform where your bot is deployed:

#### **Option A: Railway**

1. Open https://railway.app/
2. Navigate to your NIJA project
3. Click on your service (the bot)
4. Click the **"Variables"** tab
5. Add TWO new variables:
   ```
   KRAKEN_MASTER_API_KEY=<paste-your-api-key-here>
   KRAKEN_MASTER_API_SECRET=<paste-your-private-key-here>
   ```
6. **Click "Add Variable"** for each
7. Railway will **automatically restart** your service
8. Wait 2-3 minutes for restart to complete

#### **Option B: Render**

1. Open https://dashboard.render.com/
2. Select your NIJA web service
3. Click **"Environment"** tab (left sidebar)
4. Scroll to "Environment Variables"
5. Click **"Add Environment Variable"**
6. Add TWO new variables:
   ```
   Key:   KRAKEN_MASTER_API_KEY
   Value: <paste-your-api-key-here>
   
   Key:   KRAKEN_MASTER_API_SECRET
   Value: <paste-your-private-key-here>
   ```
7. Click **"Save Changes"**
8. Click **"Manual Deploy"** → "Deploy latest commit"
9. Wait 3-5 minutes for deployment

#### **Option C: Local Development**

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` file and set:
   ```bash
   KRAKEN_MASTER_API_KEY=<your-api-key>
   KRAKEN_MASTER_API_SECRET=<your-private-key>
   ```

3. **⚠️  NEVER commit the .env file** (already in .gitignore)

4. Restart the bot:
   ```bash
   ./start.sh
   ```

---

### Step 3: Verify Configuration

After restarting, check the logs for:

#### ✅ Success Indicators

```
✅ Kraken Master credentials detected
📊 Attempting to connect Kraken Pro (MASTER)...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
💰 Kraken Balance (MASTER): USD $XXX.XX
   ✅ FUNDED - Ready to trade
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING
✅ Started independent trading thread for kraken (MASTER)
```

#### ❌ Failure Indicators

If you see errors, check the specific message:

| Error Message | Solution |
|---------------|----------|
| `⚠️  Kraken MASTER connection failed: Permission denied` | Fix API key permissions (Step 1) |
| `❌ Invalid nonce` | Wait 1-2 minutes and restart |
| `❌ Invalid signature` | Credentials are incorrect, regenerate API key |
| `❌ Credentials contain only whitespace` | Remove spaces/newlines from env vars |
| `❌ KRAKEN_MASTER_API_KEY not set` | Environment variables not loaded, check deployment platform |

---

## Verification Commands

### Check Environment Variables Are Set

**Railway/Render:**
- Check the Variables/Environment tab in your dashboard
- Verify both `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET` are listed

**Local:**
```bash
python3 -c "
import os
key = os.getenv('KRAKEN_MASTER_API_KEY', '')
secret = os.getenv('KRAKEN_MASTER_API_SECRET', '')
print(f'Master Key: {\"SET\" if key else \"NOT SET\"} ({len(key)} chars)')
print(f'Master Secret: {\"SET\" if secret else \"NOT SET\"} ({len(secret)} chars)')
"
```

Expected output:
```
Master Key: SET (56 chars)
Master Secret: SET (88 chars)
```

### Test Kraken Connection

```bash
python3 diagnose_master_kraken_issue.py
```

Expected output:
```
✅ MASTER KRAKEN CONNECTED!
💰 Balance: $XXX.XX
```

### Check Bot Status

```bash
python3 check_trading_status.py
```

Look for:
```
Master Exchanges Connected: 2
  - coinbase: $X.XX
  - kraken: $XXX.XX
```

---

## Expected Results

After successful configuration:

### Before (Coinbase Only)
```
Master Exchanges: 1
├─ Coinbase: $0.76 (trading)
└─ Kraken: NOT CONNECTED ❌
```

### After (Multi-Exchange)
```
Master Exchanges: 2
├─ Coinbase: $0.76 (trading)
└─ Kraken: $XXX.XX (trading) ✅
```

**Benefits:**
- ✅ Trading on 2 exchanges instead of 1
- ✅ More market opportunities
- ✅ Better diversification
- ✅ Independent trading threads (failure isolation)

---

## Troubleshooting

### Problem: Credentials Set But Not Connecting

**Symptoms:**
```
✅ Kraken Master credentials detected
⚠️  Kraken MASTER connection failed
```

**Solutions:**

1. **Check API Key Permissions**
   - Log in to Kraken
   - Go to Settings → Security → API
   - Verify all required permissions are enabled
   - If missing permissions, create a new API key

2. **Regenerate API Key**
   - Sometimes keys get corrupted or rate-limited
   - Create a new API key on Kraken
   - Update environment variables with new credentials
   - Restart deployment

3. **Check for Whitespace Issues**
   - Ensure no extra spaces or newlines in credentials
   - Credentials should be on single line
   - No quotes needed in Railway/Render (add raw value)

4. **Verify System Time**
   - Kraken requires accurate system time for nonce validation
   - Check server time matches actual time

5. **Check Kraken API Status**
   - Visit https://status.kraken.com
   - Ensure API is operational

### Problem: Same Credentials for Master and User

**❌ WRONG:**
```bash
KRAKEN_MASTER_API_KEY="abc123"
KRAKEN_USER_TANIA_API_KEY="abc123"  # Same as master
```

**Result:** Nonce conflicts, both fail intermittently

**✅ CORRECT:**
- Create **separate API keys** for master and each user
- Each API key should be unique
- Each account should have its own credentials

---

## Security Best Practices

### ✅ DO

- ✅ Store credentials in environment variables only
- ✅ Use password manager for backup
- ✅ Enable 2-Factor Authentication on Kraken
- ✅ Set IP whitelist if possible
- ✅ Only enable required permissions
- ✅ Rotate API keys every 3-6 months
- ✅ Monitor API key usage regularly

### ❌ DON'T

- ❌ Never commit credentials to git
- ❌ Never share credentials publicly
- ❌ Never enable "Withdraw Funds" permission
- ❌ Never use same credentials for multiple accounts
- ❌ Never store credentials in code files
- ❌ Never use test/sandbox credentials (Kraken has no testnet)

---

## Additional Resources

- **[KRAKEN_MASTER_NOT_CONNECTING_JAN_16_2026.md](KRAKEN_MASTER_NOT_CONNECTING_JAN_16_2026.md)** - Detailed troubleshooting
- **[ENABLE_KRAKEN_README.md](ENABLE_KRAKEN_README.md)** - Complete Kraken setup guide
- **[MULTI_EXCHANGE_TRADING_GUIDE.md](MULTI_EXCHANGE_TRADING_GUIDE.md)** - Multi-broker architecture
- **[setup_kraken_master.py](setup_kraken_master.py)** - Interactive setup script
- **[diagnose_master_kraken_issue.py](diagnose_master_kraken_issue.py)** - Diagnostic tool

---

## Summary

**To configure Kraken Master:**

1. ✅ Get API credentials from Kraken (5 min)
2. ✅ Add `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET` to deployment platform
3. ✅ Restart deployment
4. ✅ Verify connection in logs
5. ✅ Start trading on Kraken! 🎉

**Time Required:** ~5 minutes  
**Difficulty:** Easy (just add 2 environment variables)  
**Impact:** Trading on 2 exchanges instead of 1

---

**Questions?** Run `python3 setup_kraken_master.py` for interactive setup guide.
