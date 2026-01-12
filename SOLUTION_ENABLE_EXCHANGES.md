# 🔧 SOLUTION: Connecting Kraken, OKX, and Binance Accounts

**Issue**: Exchange accounts show as "not connected" even though API keys are added to Railway/Render environment variables.

**Root Cause**: Deployments need to be **RESTARTED** after adding environment variables to load the new credentials.

**Status**: ✅ Solution provided below

---

## 🎯 Quick Fix (TL;DR)

Your API credentials ARE in Railway/Render, but the running bot instance hasn't loaded them yet.

**Railway**: Dashboard → Service → "..." menu → **"Restart Deployment"**  
**Render**: Dashboard → Service → **"Manual Deploy"** → "Deploy latest commit"

After restart, check logs for `✅ Configured` status.

---

## 📋 Complete Solution

### Step 1: Verify Your API Credentials Are Set

Run this diagnostic script to check which credentials are configured:

```bash
python3 diagnose_env_vars.py
```

**Expected output if credentials ARE set**:
```
✅ KRAKEN_MASTER_API_KEY             SET      (abcd...xyz 48 chars)
✅ KRAKEN_MASTER_API_SECRET          SET      (****...*** 64 chars)
```

**If you see "NOT SET"**:
- Credentials are NOT in the environment
- You need to add them to Railway/Render (see Step 2)

**If you see credentials as SET**:
- Great! They're in the environment
- Skip to Step 3 to restart deployment

### Step 2: Add Environment Variables (If Not Already Added)

#### For Railway:

1. Go to https://railway.app → Your Project
2. Click on your NIJA service
3. Go to **"Variables"** tab
4. Click **"+ New Variable"** and add:

   ```
   KRAKEN_MASTER_API_KEY = your-kraken-api-key
   KRAKEN_MASTER_API_SECRET = your-kraken-secret-key
   
   KRAKEN_USER_DAIVON_API_KEY = daivon-kraken-api-key
   KRAKEN_USER_DAIVON_API_SECRET = daivon-kraken-secret-key
   
   KRAKEN_USER_TANIA_API_KEY = tania-kraken-api-key
   KRAKEN_USER_TANIA_API_SECRET = tania-kraken-secret-key
   
   OKX_API_KEY = your-okx-api-key
   OKX_API_SECRET = your-okx-secret-key
   OKX_PASSPHRASE = your-okx-passphrase
   
   BINANCE_API_KEY = your-binance-api-key
   BINANCE_API_SECRET = your-binance-secret-key
   ```

5. **Important**: After adding, proceed to Step 3 to restart

#### For Render:

1. Go to https://dashboard.render.com → Your Service
2. Go to **"Environment"** tab
3. Click **"Add Environment Variable"** for each credential above
4. **Note**: Render may auto-redeploy, but if not, proceed to Step 3

### Step 3: RESTART the Deployment (CRITICAL!)

This is the step that's likely missing - environment variables are only loaded at startup.

#### Railway Restart:

1. Dashboard → Your Service
2. Click **"..."** menu (three dots) at top right
3. Select **"Restart Deployment"**
4. Wait 2-3 minutes for restart to complete

#### Render Restart:

1. Dashboard → Your Service
2. Click **"Manual Deploy"** button (top right)
3. Select **"Deploy latest commit"**
4. Wait 3-5 minutes for deployment

### Step 4: Verify Connections in Logs

After restart, check your deployment logs for:

```
🔍 EXCHANGE CREDENTIAL STATUS:
   ────────────────────────────────────────────────────────────
   📊 COINBASE (Master):
      ✅ Configured (Key: 48 chars, Secret: 64 chars)
   📊 KRAKEN (Master):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   👤 KRAKEN (User #1: Daivon):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   👤 KRAKEN (User #2: Tania):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   📊 OKX (Master):
      ✅ Configured (Key: 32 chars, Secret: 32 chars)
   📊 BINANCE (Master):
      ✅ Configured (Key: 64 chars, Secret: 64 chars)
```

Then look for connection messages:

```
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Connected to Kraken Pro API (MASTER)
   💰 Kraken balance: $1,234.56

📊 Attempting to connect OKX (MASTER)...
   ✅ Connected to OKX API (MASTER)
   💰 OKX balance: $2,345.67

📊 Attempting to connect Binance (MASTER)...
   ✅ Connected to Binance API (MASTER)
   💰 Binance balance: $3,456.78

👤 CONNECTING USER ACCOUNTS
📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $500.00

📊 Attempting to connect User #2 (Tania Gilbert) - Kraken...
   ✅ User #2 Kraken connected
   💰 User #2 Kraken balance: $750.00
```

**✅ Success!** All exchanges are connected and balances are displayed.

---

## 🔍 Troubleshooting

### Problem: Still shows "❌ Not configured" after restart

**Check 1**: Variable names are spelled correctly (case-sensitive)
- ✅ Correct: `KRAKEN_MASTER_API_KEY`
- ❌ Wrong: `kraken_master_api_key` or `KRAKEN_API_KEY`

**Check 2**: Values don't have leading/trailing spaces
- Edit each variable in Railway/Render
- Make sure there are no spaces before or after the value
- Run `diagnose_env_vars.py` - it will detect whitespace issues

**Check 3**: Values are not empty
- Make sure you pasted the actual API key/secret
- They should not be empty or contain placeholder text like "your-api-key-here"

**Check 4**: You restarted the correct service
- If you have multiple Railway projects or Render services, make sure you're on the right one

### Problem: "Invalid API key" or authentication errors

**This is different** - it means credentials ARE loaded but are incorrect:

1. **Verify credentials** are correct - copy them fresh from exchange
2. **Check API key permissions** - enable trading permissions
3. **Check API key isn't expired** - some exchanges expire keys
4. **Try regenerating keys** - delete old, create new

### Problem: Deployment keeps failing/crashing

**Check deployment logs** for Python errors:
- Look for red error messages
- Common issues:
  - Missing Python dependencies (should auto-install)
  - Invalid JSON in Coinbase credentials
  - Network issues reaching exchange APIs

---

## 🧪 Testing Locally

Before deploying, test your credentials locally:

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your real credentials
nano .env  # or use your favorite editor

# Run diagnostic
python3 diagnose_env_vars.py

# If all looks good, start the bot
./start.sh
```

---

## 📊 What Happens When You Restart?

1. **Railway/Render kills the old bot process**
2. **New container/process starts**
3. **Environment variables are loaded from platform config**
4. **Bot's start.sh script sources .env file (if present)**
5. **Bot's Python code loads credentials using os.getenv()**
6. **Connection attempts to each exchange**
7. **Success messages appear in logs**

The key is that **step 3 only happens at startup** - that's why restart is required!

---

## 🎯 Expected Results After Fix

Once properly restarted with credentials loaded, you should see:

### Master Account Trading On:
- ✅ Coinbase Advanced Trade
- ✅ Kraken Pro
- ✅ OKX
- ✅ Binance
- ✅ Alpaca (if configured)

### User #1 (Daivon Frazier) Trading On:
- ✅ Kraken Pro

### User #2 (Tania Gilbert) Trading On:
- ✅ Kraken Pro
- ✅ Alpaca (if configured)

### Trading Status:
- 🚀 **All accounts actively trading**
- 💰 **Balances displayed in logs**
- 📊 **Market scanning every 2.5 minutes**
- ⚡ **TradingView webhooks active (instant execution)**

---

## 🛠️ New Tools Provided

This update includes new diagnostic tools:

1. **`diagnose_env_vars.py`** - Comprehensive environment variable checker
   - Shows which credentials are set
   - Detects whitespace issues
   - Account-by-account status report

2. **`check_env_reload.sh`** - Force environment reload script
   - Loads .env file (for local testing)
   - Runs diagnostics
   - Provides recommendations

3. **`RESTART_DEPLOYMENT.md`** - Complete restart guide
   - Railway restart instructions
   - Render restart instructions
   - Troubleshooting tips

4. **Enhanced `start.sh`** - Shows ALL exchange credentials
   - Displays status for all 5+ exchanges
   - Character count for each credential
   - Clear visual status (✅/❌)

---

## 📝 Summary

The issue was **NOT** that credentials were missing - they ARE in Railway/Render.

The issue was that the **running bot instance needs to be RESTARTED** to load new environment variables.

**Solution**: Restart deployment via Railway/Render dashboard.

After restart, all exchanges (Kraken, OKX, Binance, Alpaca, Coinbase) will connect and trading will begin immediately!

---

## ✅ Quick Checklist

- [ ] API credentials are added to Railway/Render
- [ ] Variable names are spelled correctly (case-sensitive)
- [ ] Values have no leading/trailing spaces
- [ ] Deployment has been restarted (Railway: "Restart Deployment" / Render: "Manual Deploy")
- [ ] Waited 3-5 minutes for restart to complete
- [ ] Checked logs for `🔍 EXCHANGE CREDENTIAL STATUS:` section
- [ ] All exchanges show as `✅ Configured`
- [ ] Saw connection success messages: `✅ Connected to [Exchange]`
- [ ] Saw balance displays for each account
- [ ] No error messages in logs
- [ ] Bot shows as "Running" in platform dashboard

---

**Need help?** See detailed guides:
- `RESTART_DEPLOYMENT.md` - Complete restart instructions
- `KRAKEN_SETUP_GUIDE.md` - Kraken API setup
- `MULTI_EXCHANGE_TRADING_GUIDE.md` - Multi-exchange configuration
- Run `python3 diagnose_env_vars.py` for detailed diagnostics
