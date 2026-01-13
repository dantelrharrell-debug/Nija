# Kraken Not Connecting - Diagnosis and Solution

## 🔍 Issue Summary

**Problem:** Kraken is not connecting even though "all the env are in and all the variables are all in place."

**Root Cause:** **Kraken environment variables are NOT actually set**, despite the assumption that they are.

---

## 📊 Current Status

### What the Logs Show

```
INFO:root:✅ Connected to Coinbase Advanced Trade API
```

✅ **Coinbase IS connecting** - credentials are properly configured

```
2026-01-12 23:21:02 | INFO |    📊 Scan summary: 15 markets scanned
Error fetching candles: {"message": "too many requests."}
```

✅ **Bot IS running** and scanning markets on Coinbase

### What's Missing

❌ **NO** Kraken connection messages in the logs
❌ **NO** "✅ Kraken MASTER connected" messages
❌ **NO** Kraken trading activity

---

## 🔬 Verification

Run the diagnostic script to check Kraken credentials:

```bash
python3 check_kraken_status.py
```

**Current Output:**
```
❌ KRAKEN_MASTER_API_KEY:    NOT SET
❌ KRAKEN_MASTER_API_SECRET: NOT SET
❌ KRAKEN_USER_DAIVON_API_KEY:    NOT SET
❌ KRAKEN_USER_DAIVON_API_SECRET: NOT SET
❌ KRAKEN_USER_TANIA_API_KEY:     NOT SET
❌ KRAKEN_USER_TANIA_API_SECRET:  NOT SET

Result: ❌ NO ACCOUNTS CONFIGURED FOR KRAKEN TRADING
```

---

## 💡 Why This Is Confusing

The bot **IS** configured to support Kraken:
- ✅ `BrokerType.KRAKEN` exists in code
- ✅ `KrakenBroker` class is implemented
- ✅ Trading strategy attempts to connect to Kraken
- ✅ Multi-account support for Kraken users is ready

**BUT** the environment variables are not set, so the connection silently fails.

---

## 🎯 Solution

### Step 1: Get Kraken API Credentials

1. Go to https://www.kraken.com/u/security/api
2. Create a new API key with these permissions:
   - ✅ **Query Funds** (required to check balance)
   - ✅ **Query Open Orders & Trades** (required for position tracking)
   - ✅ **Query Closed Orders & Trades** (required for trade history)
   - ✅ **Create & Modify Orders** (required to place trades)
   - ✅ **Cancel/Close Orders** (required for stop losses)
   - ❌ **Withdraw Funds** (NOT needed - keep disabled for security)

3. Save your API key and API secret (you'll only see the secret once!)

### Step 2: Set Environment Variables

#### For Master Account (NIJA System)

```bash
export KRAKEN_MASTER_API_KEY='your-api-key-here'
export KRAKEN_MASTER_API_SECRET='your-api-secret-here'
```

#### For User #1 (Daivon Frazier)

```bash
export KRAKEN_USER_DAIVON_API_KEY='daivon-api-key'
export KRAKEN_USER_DAIVON_API_SECRET='daivon-api-secret'
```

#### For User #2 (Tania Gilbert)

```bash
export KRAKEN_USER_TANIA_API_KEY='tania-api-key'
export KRAKEN_USER_TANIA_API_SECRET='tania-api-secret'
```

### Step 3: Deploy to Railway/Render

#### **Railway**
1. Go to your Railway project dashboard
2. Click on your service
3. Navigate to **Variables** tab
4. Add each variable one by one:
   - Name: `KRAKEN_MASTER_API_KEY`
   - Value: `your-api-key-here`
5. Click **Add** for each variable
6. Railway will automatically redeploy with new variables

#### **Render**
1. Go to your Render dashboard
2. Select your web service
3. Navigate to **Environment** tab
4. Add each variable:
   - Key: `KRAKEN_MASTER_API_KEY`
   - Value: `your-api-key-here`
5. Click **Save Changes**
6. Manually trigger a deploy: **Manual Deploy** → **Deploy latest commit**

### Step 4: Verify Deployment

After the deployment restarts, you should see in the logs:

```
✅ Kraken Master credentials detected
...
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
   ✅ Kraken registered as MASTER broker in multi-account manager
```

Run the verification script again:

```bash
python3 check_kraken_status.py
```

Expected output:
```
✅ KRAKEN_MASTER_API_KEY:    SET
✅ KRAKEN_MASTER_API_SECRET: SET
Status: ✅ CONFIGURED - READY TO TRADE
```

---

## 🚨 Common Pitfalls

### 1. "I set the variables in .env but they're not working"

**Issue:** The `.env` file is not being used in Railway/Render deployments.

**Solution:** Environment variables must be set in the platform's dashboard (Railway Variables or Render Environment). The `.env` file is only for local development.

### 2. "I set the variables but forgot to restart"

**Issue:** Environment variables are loaded at startup. Changes won't take effect until restart.

**Solution:** 
- **Railway:** Service → **...** menu → **Restart Deployment**
- **Render:** Service → **Manual Deploy** → **Deploy latest commit**

### 3. "I have credentials but they have wrong permissions"

**Issue:** API key exists but lacks required permissions.

**Solution:** Edit the API key in Kraken dashboard and enable all required permissions (see Step 1).

### 4. "Variables are set but still showing NOT SET"

**Issue:** Variable names don't match exactly (case-sensitive, typos, extra spaces).

**Solution:** Double-check exact variable names:
- `KRAKEN_MASTER_API_KEY` (not `kraken_master_api_key`)
- `KRAKEN_MASTER_API_SECRET` (not `KRAKEN_MASTER_SECRET`)

---

## 📖 Related Documentation

- **KRAKEN_SETUP_GUIDE.md** - Complete Kraken setup instructions
- **MULTI_USER_SETUP_GUIDE.md** - User account setup
- **KRAKEN_CONNECTION_STATUS.md** - Detailed connection status report
- **RESTART_DEPLOYMENT.md** - How to restart on Railway/Render

---

## 🔧 Quick Diagnosis Commands

```bash
# RECOMMENDED: Enhanced diagnostic with actionable recommendations
python3 diagnose_kraken_connection.py

# Check if Kraken credentials are set (quick summary)
python3 check_kraken_status.py

# Verify all environment variables
python3 diagnose_env_vars.py

# Test Kraken connection (requires credentials to be set)
python3 verify_kraken_enabled.py
```

---

## ✅ Success Checklist

- [ ] Created Kraken API key with required permissions
- [ ] Saved API key and secret securely
- [ ] Set `KRAKEN_MASTER_API_KEY` in Railway/Render
- [ ] Set `KRAKEN_MASTER_API_SECRET` in Railway/Render
- [ ] Triggered a manual redeploy
- [ ] Verified credentials are detected in startup logs
- [ ] Confirmed "✅ Kraken MASTER connected" in logs
- [ ] Run `check_kraken_status.py` shows all ✅

---

## 💬 Support

If you've completed all steps and Kraken still isn't connecting:

1. Check the bot logs for specific error messages
2. Verify API key permissions in Kraken dashboard
3. Run `python3 check_kraken_status.py` and share the output
4. Check if there are any connection errors in the full logs

The bot will provide specific error messages if:
- API key lacks permissions → "API KEY PERMISSION ERROR"
- Rate limiting issues → "too many requests"
- Network problems → Connection timeout errors
