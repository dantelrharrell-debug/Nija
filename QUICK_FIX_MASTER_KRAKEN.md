# URGENT: Master Kraken Account Not Trading - Quick Fix

## TL;DR - Quick Answer

**Your MASTER Kraken account is not trading because the credentials are not set in your deployment platform (Railway/Render).**

**Fix in 5 minutes:**

1. **Get API Key**: https://www.kraken.com/u/security/api → Generate New Key
2. **Enable Permissions**: Query Funds, Orders (Create/Query/Cancel)
3. **Set in Railway/Render**:
   - `KRAKEN_MASTER_API_KEY=<your-key>`
   - `KRAKEN_MASTER_API_SECRET=<your-secret>`
4. **Restart** your deployment
5. **Verify** in logs: Look for "✅ Kraken MASTER connected"

**Full Guide**: See `SOLUTION_MASTER_KRAKEN_NOT_TRADING.md`

---

## What's Happening Right Now

Looking at your logs:

### ✅ WORKING:
- **Coinbase Master**: $0.76 - Trading ✓
- **Daivon's Kraken**: $30.00 - Trading ✓
- **Tania's Kraken**: $73.21 - Trading ✓

### ❌ NOT WORKING:
- **MASTER Kraken**: Not connected - NOT trading ✗

---

## Why This Happened

Your bot uses different environment variables for different accounts:

```bash
# MASTER accounts (these control YOUR trading capital)
COINBASE_API_KEY=<set>           ← ✅ SET (working)
COINBASE_API_SECRET=<set>        ← ✅ SET (working)
KRAKEN_MASTER_API_KEY=<missing>  ← ❌ NOT SET (not working)
KRAKEN_MASTER_API_SECRET=<missing> ← ❌ NOT SET (not working)

# USER accounts (these control investor/client capital)
KRAKEN_USER_DAIVON_API_KEY=<set>  ← ✅ SET (working)
KRAKEN_USER_DAIVON_API_SECRET=<set> ← ✅ SET (working)
KRAKEN_USER_TANIA_API_KEY=<set>   ← ✅ SET (working)
KRAKEN_USER_TANIA_API_SECRET=<set> ← ✅ SET (working)
```

**The issue**: You set user credentials but forgot to set master credentials.

---

## Run Diagnostic (Optional)

Want to see exactly what's wrong? Run this:

```bash
python3 diagnose_master_kraken_live.py
```

This will show:
- ❌ Which credentials are missing
- ✅ Which credentials are valid
- 🔍 Specific error if connection fails
- 📖 Step-by-step fix instructions

---

## Quick Fix Steps

### Step 1: Create Kraken Master API Key

1. Go to: https://www.kraken.com/u/security/api
2. Click "**Generate New Key**"
3. Description: `NIJA Master Trading Bot`
4. **Enable these permissions** (IMPORTANT):
   - ✅ **Query Funds**
   - ✅ **Query Open Orders & Trades**
   - ✅ **Query Closed Orders & Trades**
   - ✅ **Create & Modify Orders**
   - ✅ **Cancel/Close Orders**
   - ❌ **Do NOT enable**: Withdraw Funds (security)
5. Click "**Generate Key**"
6. **COPY** the API Key and Private Key (you'll need these next)

### Step 2A: Add to Railway

1. Go to your **Railway project**
2. Select your **service**
3. Click "**Variables**" tab
4. Click "**New Variable**"
5. Add first variable:
   - **Name**: `KRAKEN_MASTER_API_KEY`
   - **Value**: Paste your API key from Step 1
6. Add second variable:
   - **Name**: `KRAKEN_MASTER_API_SECRET`
   - **Value**: Paste your Private Key from Step 1
7. Click "**Save**" (Railway will auto-restart)

### Step 2B: Add to Render (if using Render instead)

1. Go to your **Render dashboard**
2. Select your **service**
3. Click "**Environment**" tab
4. Click "**Add Environment Variable**"
5. Add first variable:
   - **Key**: `KRAKEN_MASTER_API_KEY`
   - **Value**: Paste your API key from Step 1
6. Add second variable:
   - **Key**: `KRAKEN_MASTER_API_SECRET`
   - **Value**: Paste your Private Key from Step 1
7. Click "**Save Changes**"
8. Click "**Manual Deploy**" → "**Deploy latest commit**"

### Step 3: Verify Fix

After deployment restarts, check your logs for:

**✅ SUCCESS - Look for these messages:**
```
✅ Kraken Master credentials detected
📊 Attempting to connect Kraken Pro (MASTER)...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
...
🔍 Detecting funded brokers...
   💰 kraken: $XXX.XX
      ✅ FUNDED - Ready to trade
...
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING
🔷 STARTING MASTER BROKER THREADS
✅ Started independent trading thread for kraken (MASTER)
```

**❌ STILL FAILING? Check for:**
```
⚠️  Kraken Master credentials NOT SET
   OR
⚠️  Kraken MASTER connection failed
```

If still failing, run diagnostic:
```bash
python3 diagnose_master_kraken_live.py
```

---

## Expected Final State

After the fix, you should have **4 trading accounts**:

### MASTER Accounts (Your Capital)
1. ✅ **Coinbase Master**: $0.76
2. ✅ **Kraken Master**: $XXX.XX ← **THIS IS THE FIX**

### USER Accounts (Investor Capital)  
3. ✅ **Daivon Kraken**: $30.00
4. ✅ **Tania Kraken**: $73.21

**Total**: 4 accounts, 3 independent trading threads

---

## FAQ

### Q: Do I NEED a Master Kraken account?

**A**: No, it's optional. If you don't want to trade with your own capital on Kraken:
- **Do nothing** - leave credentials unset
- MASTER Coinbase will continue trading
- USER Kraken accounts will continue trading
- This is a valid configuration

### Q: Can I use the same API key for MASTER and USER?

**A**: **NO!** This causes nonce conflicts and both will fail.
- Each account needs its own API key
- Create separate keys at: https://www.kraken.com/u/security/api

### Q: I set the credentials but it still doesn't connect

**A**: Run diagnostic to see the exact error:
```bash
python3 diagnose_master_kraken_live.py
```

Common issues:
- **Whitespace**: Remove spaces/newlines from credentials
- **Permissions**: Enable all required permissions (see Step 1)
- **Nonce Error**: Wait 1-2 minutes and restart
- **Invalid Key**: Regenerate API key and try again

### Q: Where do profits from MASTER account go?

**A**: 
- **MASTER accounts** → Profits belong to NIJA system/owner
- **USER accounts** → Profits belong to the individual user

---

## Alternative Solutions

### Option 1: Use Only Coinbase for MASTER (Recommended if starting small)
- Keep MASTER Kraken credentials unset
- MASTER trades only on Coinbase
- USERs trade on Kraken
- Simple, no additional setup needed

### Option 2: Use Legacy Credentials (Backward Compatibility)
If you have existing Kraken credentials:
```bash
KRAKEN_API_KEY=<your-key>
KRAKEN_API_SECRET=<your-secret>
```

The bot will automatically use these for MASTER if `KRAKEN_MASTER_*` are not set.

### Option 3: Disable All Kraken Trading
Remove all Kraken credentials:
- No MASTER Kraken
- No USER Kraken
- Trade only on Coinbase

---

## Still Need Help?

### 1. Run Diagnostic
```bash
python3 diagnose_master_kraken_live.py
```

### 2. Check Full Documentation
- **Complete Guide**: `SOLUTION_MASTER_KRAKEN_NOT_TRADING.md`
- **Kraken Setup**: `KRAKEN_QUICK_START.md`
- **Multi-Exchange**: `MULTI_EXCHANGE_TRADING_GUIDE.md`

### 3. Check Logs
```bash
# View startup logs
head -n 200 nija.log

# Filter for Kraken
grep -E "Kraken|MASTER|kraken" nija.log

# Check trading status
python3 check_trading_status.py
```

### 4. Common Error Solutions

**Error: Permission denied**
→ Enable all required permissions (see Step 1 above)

**Error: Invalid nonce**  
→ Wait 1-2 minutes, then restart

**Error: Invalid signature**
→ Regenerate API key, update credentials

**Error: Credentials contain only whitespace**
→ Remove spaces/newlines from environment variables

---

## Summary

| What | Status | Action |
|------|--------|--------|
| USER Kraken accounts | ✅ Working | None needed |
| MASTER Coinbase | ✅ Working | None needed |
| MASTER Kraken | ❌ Not working | **Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET** |

**Time to fix**: 5 minutes  
**Difficulty**: Easy - just add 2 environment variables

---

**Last Updated**: January 16, 2026  
**Created**: This guide specifically addresses your reported issue  
**Status**: Ready to implement - no code changes needed, only configuration
