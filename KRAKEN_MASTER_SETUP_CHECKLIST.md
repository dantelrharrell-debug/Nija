# ✅ KRAKEN MASTER SETUP CHECKLIST

**Date:** January 17, 2026  
**Task:** Enable Kraken Master Trading Account  
**Time Required:** 5-10 minutes  

---

## 🎯 Goal

Enable your master trading account to trade on Kraken exchange.

**Current Status:** Credentials NOT configured (code is ready)  
**Target Status:** Trading on Kraken with master account

---

## 📋 Pre-Flight Check

Before starting, verify:

- [ ] I have a Kraken account (https://www.kraken.com)
- [ ] I can access Kraken API settings
- [ ] I have access to deployment environment variables (Railway/Render) or local .env file
- [ ] I understand this is for the MASTER account (my capital, not user accounts)

---

## ⚡ Setup Steps

### Step 1: Get Kraken API Credentials ⏱️ 5 min

- [ ] Go to https://www.kraken.com/u/security/api
- [ ] Click "Generate New Key" or "Add Key"
- [ ] Set description: `NIJA Master Trading Bot`
- [ ] Enable permissions:
  - [ ] ✅ Query Funds
  - [ ] ✅ Query Open Orders & Trades
  - [ ] ✅ Query Closed Orders & Trades
  - [ ] ✅ Create & Modify Orders
  - [ ] ✅ Cancel/Close Orders
  - [ ] ❌ **DO NOT** enable: Withdraw Funds
  - [ ] ❌ **DO NOT** enable: Deposit Funds
- [ ] Click "Generate Key"
- [ ] Copy API Key (public key, ~56 characters)
- [ ] Copy Private Key (secret key, ~88 characters)
- [ ] ⚠️ **IMPORTANT:** You won't see Private Key again!
- [ ] Save both keys securely (password manager recommended)

**Keys obtained:** ☐ Yes  ☐ No

---

### Step 2: Add Credentials to Deployment ⏱️ 2 min

**Choose your deployment platform:**

#### Option A: Railway

- [ ] Go to https://railway.app/
- [ ] Select your NIJA project
- [ ] Click on your service
- [ ] Click "Variables" tab
- [ ] Click "New Variable"
- [ ] Add variable:
  - Name: `KRAKEN_MASTER_API_KEY`
  - Value: `<paste-api-key-here>`
- [ ] Click "New Variable" again
- [ ] Add variable:
  - Name: `KRAKEN_MASTER_API_SECRET`
  - Value: `<paste-private-key-here>`
- [ ] Click "Save" or "Add"
- [ ] Wait for automatic restart (2-3 minutes)

**Railway configured:** ☐ Yes  ☐ Not applicable

#### Option B: Render

- [ ] Go to https://dashboard.render.com/
- [ ] Select your NIJA service
- [ ] Click "Environment" tab
- [ ] Click "Add Environment Variable"
- [ ] Add variable:
  - Key: `KRAKEN_MASTER_API_KEY`
  - Value: `<paste-api-key-here>`
- [ ] Click "Add Environment Variable" again
- [ ] Add variable:
  - Key: `KRAKEN_MASTER_API_SECRET`
  - Value: `<paste-private-key-here>`
- [ ] Click "Save Changes"
- [ ] Click "Manual Deploy" → "Deploy latest commit"
- [ ] Wait for deployment (3-5 minutes)

**Render configured:** ☐ Yes  ☐ Not applicable

#### Option C: Local Development

- [ ] Open terminal in NIJA directory
- [ ] Run: `cp .env.example .env` (if .env doesn't exist)
- [ ] Edit .env file: `nano .env` (or your preferred editor)
- [ ] Find Kraken section
- [ ] Set: `KRAKEN_MASTER_API_KEY=<your-api-key>`
- [ ] Set: `KRAKEN_MASTER_API_SECRET=<your-private-key>`
- [ ] Save and exit (Ctrl+X, Y, Enter in nano)
- [ ] ⚠️ Verify .env is in .gitignore (should be already)
- [ ] Restart bot: `./start.sh`

**Local configured:** ☐ Yes  ☐ Not applicable

---

### Step 3: Verify Setup ⏱️ 2 min

#### Quick Validation (Recommended)

- [ ] Run: `python3 validate_kraken_master_setup.py`
- [ ] Check output for: `✅ ALL CHECKS PASSED!`

**Validation passed:** ☐ Yes  ☐ No

If validation failed:
- [ ] Note the error messages
- [ ] Refer to troubleshooting section below
- [ ] Fix issues and re-run validation

#### Check Deployment Logs

- [ ] Access logs (Railway/Render dashboard or `tail -f nija.log` locally)
- [ ] Look for success messages:
  - [ ] `✅ Kraken MASTER connected`
  - [ ] `💰 Kraken Balance (MASTER): USD $XXX.XX`
  - [ ] `✅ Started independent trading thread for kraken (MASTER)`

**Logs show success:** ☐ Yes  ☐ No

#### Alternative: Check Trading Status

- [ ] Run: `python3 check_trading_status.py`
- [ ] Verify output shows:
  ```
  Master Exchanges Connected: 2
    - coinbase: $X.XX
    - kraken: $XXX.XX
  ```

**Trading status confirmed:** ☐ Yes  ☐ No

---

## ✅ Success Criteria

Setup is complete when ALL of these are true:

- [ ] ✅ Environment variables set (both KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET)
- [ ] ✅ Validation script passes all checks
- [ ] ✅ Logs show "Kraken MASTER connected"
- [ ] ✅ Logs show "Started independent trading thread for kraken"
- [ ] ✅ Trading status shows kraken in master exchanges
- [ ] ✅ No error messages in logs

**Setup complete:** ☐ Yes  ☐ No

---

## 🔧 Troubleshooting

### Error: "Credentials not configured"

**Symptoms:**
```
❌ KRAKEN_MASTER_API_KEY: NOT SET
❌ KRAKEN_MASTER_API_SECRET: NOT SET
```

**Fix:**
- [ ] Verify variables exist in deployment platform
- [ ] Check variable names are EXACT (case-sensitive)
- [ ] No typos in variable names
- [ ] Restart deployment manually if auto-restart didn't work

---

### Error: "Permission denied"

**Symptoms:**
```
⚠️  Kraken MASTER connection failed: Permission denied
```

**Fix:**
- [ ] Log in to Kraken
- [ ] Go to Security → API
- [ ] Find your API key
- [ ] Verify ALL required permissions are enabled
- [ ] If permissions wrong, DELETE old key and create new one
- [ ] Update environment variables with new key
- [ ] Restart deployment

---

### Error: "Invalid nonce"

**Symptoms:**
```
❌ Invalid nonce
```

**Fix:**
- [ ] Wait 1-2 minutes (often resolves itself)
- [ ] Restart deployment
- [ ] Verify NOT using same API key for master AND users
- [ ] If persistent: Delete old key, create new key, update vars

---

### Error: "Credentials contain only whitespace"

**Symptoms:**
```
⚠️  Kraken credentials DETECTED but INVALID
   KRAKEN_MASTER_API_KEY: SET but contains only whitespace
```

**Fix:**
- [ ] Delete both environment variables
- [ ] Re-add carefully with NO spaces before/after
- [ ] NO newlines or line breaks
- [ ] Copy directly from Kraken
- [ ] Save and restart

---

### Still Not Working?

- [ ] Read complete guide: [KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md](KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md)
- [ ] Run diagnostic: `python3 diagnose_master_kraken_issue.py`
- [ ] Check full troubleshooting section in complete guide
- [ ] Generate fresh API key if credentials might be corrupted

---

## 📝 Notes

**API Key Security:**
- ✅ Stored in environment variables (not in code)
- ✅ Backed up in password manager
- ✅ 2FA enabled on Kraken account
- ✅ Withdraw Funds permission NOT enabled
- ✅ Using separate key (not shared with user accounts)

**Additional Notes:**
```
(Add any notes specific to your setup here)




```

---

## 📊 Final Status

**Date Completed:** _______________

**Setup Status:** ☐ Complete  ☐ In Progress  ☐ Blocked

**Trading Status:**
- Coinbase Master: ☐ Active  ☐ Inactive
- Kraken Master: ☐ Active  ☐ Inactive

**Balance:**
- Kraken: $________

**Any Issues:** ☐ None  ☐ See notes above

---

## 📚 References

- **Quick Start:** [QUICKSTART_ENABLE_KRAKEN_MASTER.md](QUICKSTART_ENABLE_KRAKEN_MASTER.md)
- **Complete Guide:** [KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md](KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md)
- **Validation Script:** `validate_kraken_master_setup.py`
- **Diagnostic Script:** `diagnose_master_kraken_issue.py`
- **Kraken API Docs:** https://docs.kraken.com/rest/
- **Get API Keys:** https://www.kraken.com/u/security/api

---

**Last Updated:** January 17, 2026  
**Version:** 1.0
