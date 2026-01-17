# Complete Kraken Master Account Setup Guide

**Last Updated:** January 17, 2026  
**Status:** ✅ Code infrastructure complete - Only credentials needed  
**Time Required:** 5-10 minutes  

---

## 📋 Table of Contents

1. [Quick Start (5 Minutes)](#quick-start-5-minutes)
2. [Understanding the Setup](#understanding-the-setup)
3. [Kraken API Best Practices](#kraken-api-best-practices)
4. [Step-by-Step Instructions](#step-by-step-instructions)
5. [Deployment Platform Setup](#deployment-platform-setup)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)
8. [Security Best Practices](#security-best-practices)

---

## 🚀 Quick Start (5 Minutes)

### Current Status Check

Run this command to see your current configuration:

```bash
python3 diagnose_master_kraken_issue.py
```

**Expected Output:**
```
❌ KRAKEN_MASTER_API_KEY: NOT SET
❌ KRAKEN_MASTER_API_SECRET: NOT SET
```

### What You Need

**Two environment variables:**
- `KRAKEN_MASTER_API_KEY` - Your Kraken API public key (~56 characters)
- `KRAKEN_MASTER_API_SECRET` - Your Kraken API private key (~88 characters)

**That's it!** The code infrastructure is already in place.

---

## 🎯 Understanding the Setup

### Why Is Master Account Not Trading?

NIJA supports multiple independent trading accounts:

**✅ Currently Active:**
- Coinbase Master: Trading with your capital
- Kraken User #1 (daivon_frazier): Trading (if credentials set)
- Kraken User #2 (tania_gilbert): Trading (if credentials set)

**❌ Currently NOT Active:**
- **Kraken Master**: NOT trading (credentials not configured)

**The Issue:** Master Kraken account credentials are not set in your deployment environment variables.

**The Solution:** Add 2 environment variables to your deployment platform (Railway, Render, or local .env).

### What This Enables

**After setup, you'll have:**
- ✅ Trading on 2+ exchanges (Coinbase + Kraken) instead of 1
- ✅ More market opportunities and diversification
- ✅ Independent trading threads (one exchange failing won't affect others)
- ✅ Better capital allocation across exchanges

---

## 📚 Kraken API Best Practices

### Required API Permissions

Based on Kraken documentation and forums, your API key MUST have these permissions:

**✅ Required (for trading bot):**
- ✅ **Query Funds** - Check account balances
- ✅ **Query Open Orders & Trades** - Track current orders
- ✅ **Query Closed Orders & Trades** - Track historical trades
- ✅ **Create & Modify Orders** - Place new orders
- ✅ **Cancel/Close Orders** - Cancel existing orders

**❌ DO NOT Enable:**
- ❌ **Withdraw Funds** - Security risk, not needed for trading
- ❌ **Deposit Funds** - Not needed for trading bot

### Avoiding Nonce Errors

**What is a nonce?** A unique, ever-increasing number sent with each API request to prevent replay attacks.

**Common nonce issues:**
- Multiple scripts using the same API key (most common cause)
- System clock not synced (use NTP)
- Reusing old API keys

**Best practices (already implemented in NIJA):**
- ✅ Use separate API keys for master and each user account
- ✅ Single process per API key (NIJA handles this)
- ✅ Microsecond-precision nonce with monotonic increase
- ✅ 5-second delay between connections to same broker
- ✅ Automatic retry with exponential backoff

**NIJA's nonce implementation:**
```python
# Uses microseconds + tracking for strict monotonic increase
# Prevents duplicate nonces even with multiple requests per second
# Random 0-5 second offset per broker instance
# 5-second delay between sequential connections
```

### Rate Limiting

Kraken enforces API rate limits based on account tier. NIJA's implementation:
- ✅ Built-in rate limiter via pykrakenapi
- ✅ Request throttling to prevent bans
- ✅ Automatic retry with exponential backoff
- ✅ 30-second timeout on HTTP requests

---

## 📝 Step-by-Step Instructions

### Step 1: Get Kraken API Credentials

1. **Log in to Kraken**: https://www.kraken.com

2. **Navigate to API Settings**:
   - Click on your profile (top right)
   - Select "Security" → "API"
   - Or direct link: https://www.kraken.com/u/security/api

3. **Generate New API Key**:
   - Click **"Generate New Key"** or **"Add Key"**
   - Description: `NIJA Master Trading Bot`
   
4. **Set Permissions** (CRITICAL):
   ```
   ✅ Query Funds
   ✅ Query Open Orders & Trades
   ✅ Query Closed Orders & Trades  
   ✅ Create & Modify Orders
   ✅ Cancel/Close Orders
   ❌ Withdraw Funds (NEVER enable)
   ❌ Deposit Funds (not needed)
   ```

5. **Optional Settings**:
   - Nonce Window: Leave default (0) or set to 10000
   - WebSocket API: ✅ Enable (for real-time data)
   - IP Whitelist: Set if you have a static IP

6. **Generate Key**:
   - Click **"Generate Key"**
   - **⚠️ IMPORTANT:** Copy BOTH keys immediately:
     - **API Key** (public key, ~56 chars)
     - **Private Key** (secret key, ~88 chars)
   - **You won't see the Private Key again!**

7. **Store Securely**:
   - Save to password manager
   - Never share or commit to git
   - Keep backup in secure location

### Step 2: Verify Your Keys

Before adding to deployment, verify the keys:

**API Key format:**
- Length: ~56 characters
- Example: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6`

**Private Key format:**
- Length: ~88 characters (base64 encoded)
- Example: `ABC123def456GHI789jkl012MNO345pqr678STU901vwx234YZA567bcd890...`

**⚠️ Common mistakes:**
- Extra spaces before/after the keys
- Missing characters from copy/paste
- Using same key for master and user accounts

---

## 🚀 Deployment Platform Setup

### Option A: Railway (Recommended)

**If using Railway for deployment:**

1. **Open Railway Dashboard**:
   - Go to https://railway.app/
   - Select your NIJA project
   - Click on your service

2. **Add Environment Variables**:
   - Click **"Variables"** tab
   - Click **"New Variable"**

3. **Add First Variable**:
   ```
   Name:  KRAKEN_MASTER_API_KEY
   Value: <paste-your-api-key-here>
   ```
   - Click **"Add"**

4. **Add Second Variable**:
   ```
   Name:  KRAKEN_MASTER_API_SECRET
   Value: <paste-your-private-key-here>
   ```
   - Click **"Add"**

5. **Deploy**:
   - Railway will **automatically restart** your service
   - Wait 2-3 minutes for deployment
   - Check logs for success messages

### Option B: Render

**If using Render for deployment:**

1. **Open Render Dashboard**:
   - Go to https://dashboard.render.com/
   - Select your NIJA web service

2. **Navigate to Environment**:
   - Click **"Environment"** tab (left sidebar)
   - Scroll to "Environment Variables"

3. **Add Variables**:
   - Click **"Add Environment Variable"**
   
   **Variable 1:**
   ```
   Key:   KRAKEN_MASTER_API_KEY
   Value: <paste-your-api-key-here>
   ```
   
   **Variable 2:**
   ```
   Key:   KRAKEN_MASTER_API_SECRET
   Value: <paste-your-private-key-here>
   ```

4. **Save and Deploy**:
   - Click **"Save Changes"**
   - Click **"Manual Deploy"** → **"Deploy latest commit"**
   - Wait 3-5 minutes for deployment

### Option C: Local Development

**If running locally:**

1. **Copy .env.example**:
   ```bash
   cd /path/to/Nija
   cp .env.example .env
   ```

2. **Edit .env file**:
   ```bash
   nano .env
   # or use your preferred editor
   ```

3. **Add Credentials**:
   ```bash
   # Find the Kraken section and add:
   KRAKEN_MASTER_API_KEY=<your-api-key>
   KRAKEN_MASTER_API_SECRET=<your-private-key>
   ```

4. **Save and Exit**:
   - In nano: Ctrl+X, then Y, then Enter
   - ⚠️ **NEVER commit .env file** (already in .gitignore)

5. **Restart Bot**:
   ```bash
   ./start.sh
   ```

---

## ✅ Verification

### Check Logs for Success

After deployment restarts, check logs for these indicators:

**✅ Success Messages:**
```
📊 Attempting to connect Kraken Pro (MASTER)...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
💰 Kraken Balance (MASTER): USD $XXX.XX
   ✅ FUNDED - Ready to trade
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING
✅ Started independent trading thread for kraken (MASTER)
```

**❌ Failure Messages:**
```
⚠️  Kraken credentials not configured for MASTER (skipping)
⚠️  Kraken MASTER connection failed: Permission denied
❌ Invalid nonce
❌ Invalid signature
```

### Run Diagnostic Script

```bash
python3 diagnose_master_kraken_issue.py
```

**Expected success output:**
```
✅ KRAKEN_MASTER_API_KEY: SET (56 characters)
✅ KRAKEN_MASTER_API_SECRET: SET (88 characters)
✅ MASTER KRAKEN CONNECTED!
💰 Balance: $XXX.XX
```

### Check Trading Status

```bash
python3 check_trading_status.py
```

**Look for:**
```
Master Exchanges Connected: 2
  - coinbase: $X.XX
  - kraken: $XXX.XX
```

### Verify Environment Variables

**Railway/Render:**
- Go to Variables/Environment tab in dashboard
- Verify both variables are listed
- Check for typos in variable names

**Local:**
```bash
python3 -c "
import os
key = os.getenv('KRAKEN_MASTER_API_KEY', '')
secret = os.getenv('KRAKEN_MASTER_API_SECRET', '')
print(f'Key: {\"SET\" if key else \"NOT SET\"} ({len(key)} chars)')
print(f'Secret: {\"SET\" if secret else \"NOT SET\"} ({len(secret)} chars)')
"
```

---

## 🔧 Troubleshooting

### Error: "Kraken credentials not configured"

**Cause:** Environment variables not set or not saved properly.

**Fix:**
1. Verify variables exist in Railway/Render dashboard
2. Check variable names are EXACT:
   - `KRAKEN_MASTER_API_KEY` (case-sensitive)
   - `KRAKEN_MASTER_API_SECRET` (case-sensitive)
3. No typos, correct spelling
4. Manually restart deployment if auto-restart didn't work

### Error: "Permission denied"

**Cause:** API key missing required permissions.

**Fix:**
1. Log in to Kraken
2. Go to Settings → Security → API
3. Find your API key
4. Verify ALL required permissions are enabled:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
5. If missing permissions:
   - **Delete the old key**
   - Create new key with correct permissions
   - Update environment variables
   - Restart deployment

### Error: "Invalid nonce"

**Cause:** Nonce synchronization issue (usually temporary).

**Common causes:**
- System clock not synced
- Same API key used for multiple accounts
- API key created while another request was in progress

**Fix:**
1. **Wait 1-2 minutes** (often resolves itself)
2. Restart your deployment
3. Verify you're NOT using the same API key for master AND users
4. If persistent:
   - Delete old API key
   - Create fresh API key
   - Update environment variables
   - Restart deployment

### Error: "Credentials contain only whitespace"

**Cause:** Copy/paste added invisible spaces or newlines.

**Fix:**
1. Go to Railway/Render environment variables
2. **Delete** both variables
3. **Re-add** carefully:
   - NO spaces before/after values
   - NO newlines/line breaks
   - Copy directly from Kraken
4. Save and restart

### Error: "Invalid signature"

**Cause:** API keys are incorrect or corrupted.

**Fix:**
1. Verify you copied the COMPLETE key (all characters)
2. Check for truncated keys (missing characters)
3. Regenerate API key if needed
4. Ensure no special characters were modified during copy/paste

### Still Not Working?

**1. Full diagnostic:**
```bash
python3 diagnose_master_kraken_issue.py > diagnostic_output.txt
cat diagnostic_output.txt
```

**2. Check full logs:**
- Railway: View deployment logs in dashboard
- Render: View logs in dashboard
- Local: `tail -f nija.log`

**3. Generate fresh API key:**
- Delete old key on Kraken
- Create new key with all permissions
- Update environment variables
- Restart service

**4. Verify system requirements:**
- Python 3.11+
- krakenex==2.2.2
- pykrakenapi==0.3.2
- Installed via: `pip install -r requirements.txt`

---

## 🔒 Security Best Practices

### ✅ DO

- ✅ **Store credentials in environment variables only**
  - Never hard-code in source files
  - Use deployment platform's secret management

- ✅ **Use password manager for backup**
  - 1Password, LastPass, Bitwarden, etc.
  - Encrypted storage

- ✅ **Enable 2-Factor Authentication on Kraken**
  - Protect your account
  - Separate from API keys

- ✅ **Set IP whitelist if possible**
  - Restricts API access to your server IP
  - Additional security layer

- ✅ **Only enable required permissions**
  - Never enable Withdraw Funds
  - Minimize attack surface

- ✅ **Use separate API keys per account**
  - Master gets its own key
  - Each user gets their own key
  - Prevents nonce conflicts

- ✅ **Rotate API keys regularly**
  - Every 3-6 months
  - After any security incident

- ✅ **Monitor API key usage**
  - Check Kraken dashboard regularly
  - Watch for unexpected activity

- ✅ **Keep libraries updated**
  ```bash
  pip install --upgrade krakenex pykrakenapi
  ```

### ❌ DON'T

- ❌ **Never commit credentials to git**
  - .env is in .gitignore
  - Double-check before commits

- ❌ **Never share credentials publicly**
  - No screenshots with keys visible
  - No pasting in Discord/Slack

- ❌ **Never enable "Withdraw Funds" permission**
  - Major security risk
  - Not needed for trading

- ❌ **Never use same credentials for multiple accounts**
  - Causes nonce conflicts
  - Both accounts will fail

- ❌ **Never store credentials in code files**
  - Always use environment variables
  - Never in config.py or similar

- ❌ **Never run on untrusted servers**
  - Only use reputable hosting
  - Keep servers updated

### If API Key Compromised

**Immediate actions:**
1. **Revoke the key** on Kraken immediately
2. **Generate new key** with fresh credentials
3. **Update environment variables** in deployment
4. **Check account activity** for unauthorized trades
5. **Change Kraken password** if suspicious
6. **Review security logs** on Kraken
7. **Contact Kraken support** if needed

---

## 📊 Expected Results

### Before Setup

```
Master Exchanges: 1
├─ Coinbase: $0.76 (trading)
└─ Kraken: NOT CONNECTED ❌
```

### After Setup

```
Master Exchanges: 2
├─ Coinbase: $0.76 (trading)
└─ Kraken: $XXX.XX (trading) ✅
```

**Benefits:**
- ✅ 2x exchange coverage
- ✅ More trading opportunities
- ✅ Better risk diversification
- ✅ Independent trading threads
- ✅ Failure isolation (one exchange failing doesn't affect the other)

---

## 🎯 Final Checklist

Before considering setup complete:

- [ ] Created Kraken API key with ALL required permissions
- [ ] Did NOT enable "Withdraw Funds" permission
- [ ] Saved BOTH API Key and Private Key securely
- [ ] Added `KRAKEN_MASTER_API_KEY` to deployment
- [ ] Added `KRAKEN_MASTER_API_SECRET` to deployment
- [ ] Verified variable names are spelled correctly
- [ ] Verified no extra spaces/newlines in values
- [ ] Deployment restarted after adding variables
- [ ] Checked logs for success messages
- [ ] Ran `diagnose_master_kraken_issue.py` - shows CONNECTED
- [ ] Verified Kraken balance shows in bot
- [ ] Independent trading thread started for Kraken

---

## 📚 Additional Resources

### Documentation
- [SETUP_KRAKEN_MASTER_QUICK.md](SETUP_KRAKEN_MASTER_QUICK.md) - 5-minute quick reference
- [CONFIGURE_KRAKEN_MASTER.md](CONFIGURE_KRAKEN_MASTER.md) - Detailed configuration guide
- [ENABLE_MASTER_KRAKEN_TRADING.md](ENABLE_MASTER_KRAKEN_TRADING.md) - Trading enablement guide
- [KRAKEN_QUICK_START.md](KRAKEN_QUICK_START.md) - General Kraken setup
- [MULTI_EXCHANGE_TRADING_GUIDE.md](MULTI_EXCHANGE_TRADING_GUIDE.md) - Multi-broker architecture

### Scripts
- `diagnose_master_kraken_issue.py` - Diagnostic tool
- `setup_kraken_master.py` - Interactive setup wizard
- `check_trading_status.py` - Overall status check
- `test_kraken_connection_live.py` - Live connection test

### External Links
- [Kraken API Documentation](https://docs.kraken.com/rest/)
- [Kraken API Key Creation](https://www.kraken.com/u/security/api)
- [krakenex GitHub](https://github.com/veox/python3-krakenex)
- [pykrakenapi GitHub](https://github.com/dominiktraxl/pykrakenapi)
- [Kraken API Status](https://status.kraken.com)

---

## 🆘 Need Help?

### Self-Service Troubleshooting

1. **Run full diagnostic**:
   ```bash
   python3 diagnose_master_kraken_issue.py > diagnostic.txt
   python3 check_trading_status.py >> diagnostic.txt
   ```

2. **Check deployment logs**:
   - Copy any error messages
   - Note timestamps of failures

3. **Review this guide** thoroughly
   - Most issues covered in Troubleshooting section

### Getting Support

If you've followed all steps and still having issues:

1. **Gather information**:
   - Output of `diagnose_master_kraken_issue.py`
   - Deployment platform logs (last 100 lines)
   - Which deployment platform (Railway/Render/Local)
   - Confirmation you followed all checklist items

2. **Create GitHub issue** with:
   - Clear description of the problem
   - All diagnostic output
   - Steps you've already tried
   - Error messages from logs
   - **DO NOT include actual API keys!**

3. **Check existing issues**:
   - Your problem may already be solved
   - Search GitHub issues first

---

## ✨ Summary

**What you need:**
- 2 environment variables (KRAKEN_MASTER_API_KEY, KRAKEN_MASTER_API_SECRET)

**Where to get them:**
- https://www.kraken.com/u/security/api

**Where to set them:**
- Railway: Variables tab
- Render: Environment tab  
- Local: .env file

**Time required:**
- 5-10 minutes

**Difficulty:**
- Easy (just adding environment variables)

**Impact:**
- Trading on 2+ exchanges instead of 1
- Better diversification and more opportunities

---

**Issue**: Master Kraken not trading  
**Root Cause**: Credentials not set in environment  
**Solution**: Add 2 environment variables  
**Status**: ✅ Code ready - Only configuration needed  

**Last Updated**: January 17, 2026
