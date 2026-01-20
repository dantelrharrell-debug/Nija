# Kraken User Trading - Deployment Guide

**Status:** ✅ READY FOR DEPLOYMENT
**Date:** January 20, 2026
**Users:** Daivon Frazier & Tania Gilbert

---

## 🔒 Locked Credentials Overview

The Kraken API credentials for Daivon Frazier and Tania Gilbert have been locked and are ready for deployment. These credentials are stored in `.env.kraken_users_locked` file.

### Users Configured:

| User ID | Name | Broker | Status |
|---------|------|--------|--------|
| `daivon_frazier` | Daivon Frazier | Kraken | ✅ Enabled |
| `tania_gilbert` | Tania Gilbert | Kraken | ✅ Enabled |

---

## 📋 Pre-Deployment Checklist

Before deploying, verify the following:

- [x] User configuration files exist and are enabled
  - `config/users/retail_kraken.json` contains both users
  - Both users have `"enabled": true`
- [x] Credentials are in the correct format
  - API keys are 50+ characters
  - API secrets are 80+ characters
- [x] Locked credentials file created
  - `.env.kraken_users_locked` contains all 4 environment variables
- [ ] Validate credentials (run validation script)
- [ ] Deploy to platform
- [ ] Verify trading is active

---

## 🔧 Step 1: Validate Credentials (REQUIRED)

Before deploying to production, test the credentials locally:

```bash
# Option A: Using the locked credentials file
python3 verify_kraken_user_credentials.py

# Option B: Test with environment variables set
export KRAKEN_USER_DAIVON_API_KEY="HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+"
export KRAKEN_USER_DAIVON_API_SECRET="6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ=="
export KRAKEN_USER_TANIA_API_KEY="XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/"
export KRAKEN_USER_TANIA_API_SECRET="iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw=="
python3 verify_kraken_user_credentials.py
```

**Expected Output:**
```
✅ ALL CREDENTIALS VALIDATED SUCCESSFULLY
🚀 READY FOR DEPLOYMENT
```

**If validation fails:**
- Check that Kraken SDK is installed: `pip install krakenex pykrakenapi`
- Verify API keys at https://www.kraken.com/u/security/api
- Ensure API keys have the required permissions (see Security section)

---

## 🚀 Step 2: Deploy to Platform

### Option A: Railway Deployment

1. **Go to Railway Dashboard**
   - Navigate to https://railway.app/dashboard
   - Select your NIJA project
   - Click on your service

2. **Add Environment Variables**
   - Click on "Variables" tab
   - Click "New Variable" for each of the following:

   ```
   KRAKEN_USER_DAIVON_API_KEY
   HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+

   KRAKEN_USER_DAIVON_API_SECRET
   6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ==

   KRAKEN_USER_TANIA_API_KEY
   XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/

   KRAKEN_USER_TANIA_API_SECRET
   iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
   ```

3. **Deploy**
   - Railway will automatically trigger a redeploy
   - Wait ~2-3 minutes for deployment to complete

### Option B: Render Deployment

1. **Go to Render Dashboard**
   - Navigate to https://dashboard.render.com
   - Select your NIJA service

2. **Add Environment Variables**
   - Click "Environment" tab
   - Click "Add Environment Variable" for each variable
   - Copy the exact names and values from above

3. **Deploy**
   - Click "Save Changes"
   - Click "Manual Deploy" → "Deploy latest commit"
   - Wait for deployment to complete

### Option C: Local/Docker Deployment

1. **Copy locked credentials to .env**
   ```bash
   # Option A: Copy entire file
   cp .env.kraken_users_locked .env

   # Option B: Append to existing .env
   cat .env.kraken_users_locked >> .env
   ```

2. **Start the bot**
   ```bash
   ./start.sh
   ```

---

## ✅ Step 3: Verify Deployment

After deployment, check the logs to confirm trading is active:

### Expected Log Messages:

```
🔍 EXCHANGE CREDENTIAL STATUS:
   ────────────────────────────────────────────────────────
   👤 KRAKEN (User #1: Daivon):
      ✅ Configured (Key: 60 chars, Secret: 88 chars)
   👤 KRAKEN (User #2: Tania):
      ✅ Configured (Key: 60 chars, Secret: 88 chars)
   ────────────────────────────────────────────────────────
```

```
✓ Kraken User #1 (Daivon) credentials detected
✓ Kraken User #2 (Tania) credentials detected
```

```
✓ User broker added: daivon_frazier -> Kraken
✓ User broker added: tania_gilbert -> Kraken
```

```
🚀 USER: Daivon Frazier: TRADING (Broker: KRAKEN)
🚀 USER: Tania Gilbert: TRADING (Broker: KRAKEN)
```

### If you see errors:

❌ **"Kraken credentials not configured"**
- Variables are not set correctly on the platform
- Double-check variable names (case-sensitive)
- Ensure no extra spaces in values

❌ **"Invalid nonce"**
- Clear deployment cache and redeploy
- May resolve automatically after first connection

❌ **"Permission denied"**
- API keys lack required permissions
- Go to https://www.kraken.com/u/security/api
- Regenerate keys with correct permissions (see Security section)

❌ **"Kraken SDK not installed"**
- Deployment is using NIXPACKS instead of Dockerfile
- Update `railway.json` to use `"builder": "DOCKERFILE"`
- Trigger a fresh deployment (not just restart)

---

## 🔐 Security Configuration

### Required API Key Permissions

Each user must create a Kraken API key with these permissions:

**REQUIRED PERMISSIONS:**
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders

**MUST BE DISABLED:**
- ❌ Withdraw Funds (for safety)

### Create API Keys at Kraken:

1. Go to https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set Key Description: "NIJA Trading Bot"
4. Select the required permissions above
5. **Uncheck** "Withdraw Funds"
6. Click "Generate Key"
7. **IMPORTANT:** Copy the API Key and Private Key immediately (they won't be shown again)

### Security Best Practices:

- 🔒 Never commit `.env` or `.env.kraken_users_locked` to git
- 🔒 Don't share API keys publicly
- 🔒 Use separate API keys for each user (no shared keys)
- 🔒 Regularly review API activity at Kraken.com
- 🔒 If credentials are compromised, immediately revoke at Kraken.com

---

## 📊 Trading Configuration

### User Settings (Already Configured)

Both users are configured in `config/users/retail_kraken.json`:

```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  },
  {
    "user_id": "tania_gilbert",
    "name": "Tania Gilbert",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  }
]
```

### Trading Parameters

The bot will use these default settings for both users:

- **Minimum Cash to Buy:** $5.50 (configurable via `MIN_CASH_TO_BUY`)
- **Minimum Trading Balance:** $25.00 (configurable via `MINIMUM_TRADING_BALANCE`)
- **Max Concurrent Positions:** 7 per user
- **Strategy:** APEX v7.1 (Dual RSI + Trailing Stop)

---

## 🐛 Troubleshooting

### Problem: User not trading

**Check logs for:**
```
⚠️ Kraken credentials not configured for USER:daivon_frazier (skipping)
```

**Solution:**
- Verify environment variables are set on platform
- Variable names must be exact (case-sensitive)
- Check for whitespace in values

### Problem: "Invalid nonce" errors

**Solution:**
- Kraken nonce issues usually resolve automatically
- Clear deployment cache and redeploy
- Bot uses global nonce manager to prevent conflicts

### Problem: "Insufficient permissions"

**Solution:**
- Recreate API keys with all required permissions
- Update environment variables with new credentials
- Redeploy

### Problem: SDK not installed

**Solution:**
- Ensure using Dockerfile (not NIXPACKS)
- Check `requirements.txt` includes: `krakenex`, `pykrakenapi`
- Trigger fresh deployment (not restart)

---

## 📞 Support

If you encounter issues after following this guide:

1. **Check logs first** - Most issues are visible in deployment logs
2. **Run validation script** - `verify_kraken_user_credentials.py` catches common issues
3. **Review error messages** - Bot provides detailed error context
4. **Check Kraken API status** - https://status.kraken.com

---

## ✅ Deployment Complete Checklist

After deployment, verify:

- [ ] Both users show "✅ Configured" in startup logs
- [ ] Bot logs show "credentials detected" for both users
- [ ] Bot logs show "User broker added" for both users
- [ ] Bot logs show "TRADING (Broker: KRAKEN)" for both users
- [ ] No error messages in logs
- [ ] Trading activity begins (check positions/orders)

**Once all items are checked, Kraken user trading is LIVE! 🚀**

---

**Last Updated:** January 20, 2026
**Status:** ✅ READY FOR PRODUCTION DEPLOYMENT
