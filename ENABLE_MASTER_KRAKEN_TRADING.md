# Enable Master Kraken Trading - Simple Guide

## TL;DR - The Quick Fix

Your users ARE trading on Kraken, but your MASTER account is not. Here's why and how to fix it:

**Problem**: Master Kraken credentials are not set in your deployment environment (Railway or Render).

**Solution**: Add these 2 environment variables to your deployment:
- `KRAKEN_MASTER_API_KEY`
- `KRAKEN_MASTER_API_SECRET`

**Time**: 5-10 minutes

---

## Understanding the Issue

NIJA supports multiple trading accounts:

### MASTER Accounts (Your Capital)
- **Coinbase Master**: ✅ Trading (credentials set)
- **Kraken Master**: ❌ NOT trading (credentials NOT set) ← **THIS IS THE ISSUE**

### USER Accounts (Investor/Client Capital)
- **User: tania_gilbert (Kraken)**: ✅ Trading (credentials set)
- **User: daivon_frazier (Kraken)**: ✅ Trading (credentials set)

**The Result**: Users can trade on Kraken, but master cannot because master credentials weren't configured.

---

## Run the Quick Fix Script

Before making any changes, run this diagnostic script to see exactly what's configured:

```bash
python3 quick_fix_master_kraken.py
```

This will:
- ✅ Show which credentials are set
- ❌ Identify what's missing
- 📖 Provide step-by-step fix instructions
- 🔌 Test the connection (if credentials are set)

---

## Step-by-Step Fix

### 1. Get Kraken API Credentials

1. Go to: **https://www.kraken.com/u/security/api**
2. Click **"Generate New Key"**
3. Description: `NIJA Master Trading Bot`
4. **Enable these permissions** (REQUIRED):
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **Do NOT enable**: Withdraw Funds (security risk)
5. Click **"Generate Key"**
6. **SAVE BOTH**:
   - **API Key** (public)
   - **Private Key** (secret)

⚠️ **IMPORTANT**: Use a **DIFFERENT** API key than what you use for user accounts. Using the same key causes nonce conflicts and both will fail.

---

### 2A. Add Credentials to Railway

If you're using Railway:

1. Go to your **Railway dashboard**
2. Select your **NIJA service**
3. Click the **"Variables"** tab
4. Click **"New Variable"**
5. Add:
   ```
   Name:  KRAKEN_MASTER_API_KEY
   Value: <paste your API Key from step 1>
   ```
6. Click **"New Variable"** again
7. Add:
   ```
   Name:  KRAKEN_MASTER_API_SECRET
   Value: <paste your Private Key from step 1>
   ```
8. Click **"Save"**
9. Railway will **automatically restart** your service

✅ Done! Wait 1-2 minutes for the service to restart.

---

### 2B. Add Credentials to Render

If you're using Render:

1. Go to your **Render dashboard**
2. Select your **NIJA service**
3. Click the **"Environment"** tab
4. Click **"Add Environment Variable"**
5. Add:
   ```
   Key:   KRAKEN_MASTER_API_KEY
   Value: <paste your API Key from step 1>
   ```
6. Click **"Add Environment Variable"** again
7. Add:
   ```
   Key:   KRAKEN_MASTER_API_SECRET
   Value: <paste your Private Key from step 1>
   ```
8. Click **"Save Changes"**
9. Click **"Manual Deploy"** → **"Deploy latest commit"**

✅ Done! Wait 1-2 minutes for the deployment to complete.

---

### 3. Verify the Fix

After your service restarts, check the logs for these success messages:

**✅ SUCCESS - Look for:**
```
📊 Attempting to connect Kraken Pro (MASTER)...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
...
🔍 Detecting funded brokers...
   💰 kraken: $XXX.XX
      ✅ FUNDED - Ready to trade
...
✅ Started independent trading thread for kraken (MASTER)
```

**❌ STILL FAILING? - Look for:**
```
⚠️  Kraken credentials not configured for MASTER (skipping)
   OR
⚠️  Kraken MASTER connection failed
```

If you see failure messages:
1. Run the diagnostic: `python3 quick_fix_master_kraken.py`
2. Check for specific error details
3. See troubleshooting section below

---

## Expected Final State

After the fix, you should have **4 independent trading accounts**:

### Master Accounts (Your Capital)
1. ✅ **Coinbase Master**: $X.XX - Trading
2. ✅ **Kraken Master**: $X.XX - Trading ← **NEWLY ENABLED**

### User Accounts (Investor Capital)
3. ✅ **daivon_frazier (Kraken)**: $X.XX - Trading
4. ✅ **tania_gilbert (Kraken)**: $X.XX - Trading

**Total**: 4 accounts, 4 independent trading threads across 2 exchanges

---

## Troubleshooting

### ❌ Error: "Kraken credentials not configured"

**Cause**: Environment variables are not set or not saved properly.

**Fix**:
1. Go back to Railway/Render dashboard
2. Verify the variables are actually saved
3. Make sure variable names are EXACTLY:
   - `KRAKEN_MASTER_API_KEY` (no typos, correct case)
   - `KRAKEN_MASTER_API_SECRET` (no typos, correct case)
4. Restart the service manually if auto-restart didn't work

---

### ❌ Error: "Permission denied"

**Cause**: API key doesn't have required permissions.

**Fix**:
1. Go to: https://www.kraken.com/u/security/api
2. Find your API key
3. Verify all required permissions are enabled (see Step 1 above)
4. If permissions are wrong, **delete the key** and create a new one
5. Update the environment variables with the new key
6. Restart the service

---

### ❌ Error: "Invalid nonce"

**Cause**: Kraken API nonce synchronization issue (usually temporary).

**Fix**:
1. **Wait 1-2 minutes** (this often resolves itself)
2. Restart your service
3. If it persists, check that you're not using the same API key for master AND user accounts

---

### ❌ Error: "Credentials contain only whitespace"

**Cause**: Copy/paste added invisible spaces or newlines.

**Fix**:
1. Go to Railway/Render environment variables
2. **Delete** both `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`
3. **Re-add** them carefully:
   - Make sure there are NO spaces before or after the values
   - Make sure there are NO newlines/line breaks
   - Copy/paste directly from Kraken without extra characters
4. Save and restart

---

### ❌ Still Not Working?

1. **Run the diagnostic**:
   ```bash
   python3 quick_fix_master_kraken.py
   ```

2. **Check full logs**:
   ```bash
   # In your deployment platform (Railway/Render)
   # View the application logs
   # Look for specific error messages
   ```

3. **Generate a fresh API key**:
   - Sometimes keys get corrupted or rate-limited
   - Delete old key, create new one
   - Update environment variables
   - Restart service

4. **Verify system time**:
   - Kraken requires accurate system time for nonce validation
   - This is usually not an issue on Railway/Render

---

## Alternative: Don't Want Master Kraken?

If you don't want to trade with your own capital on Kraken, that's fine:

**Option 1**: **Do Nothing** (Recommended if starting small)
- Leave master Kraken credentials unset
- Master trades only on Coinbase
- Users trade on Kraken
- This is a valid configuration

**Option 2**: Use Legacy Credentials
If you have existing `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` variables set, the bot will automatically use them for the master account. This provides backward compatibility.

---

## FAQ

### Q: Do I need separate Kraken accounts for master and users?

**A**: No, you don't need separate Kraken ACCOUNTS, but you DO need separate API KEYS. All keys can be from the same Kraken account, but each trading account (master, user1, user2, etc.) needs its own unique API key to avoid nonce conflicts.

### Q: Will this affect my existing user trading?

**A**: No! User accounts will continue trading normally. Adding master Kraken just adds another independent trading thread.

### Q: How much should I fund the master Kraken account?

**A**: Start small to test ($25-$100). You can always add more later. The bot enforces a minimum balance of $0.50 to allow trading, but $25+ is recommended for optimal performance.

### Q: Can I use the same API key for master that I use for users?

**A**: **NO!** This is the most common mistake. Each account MUST have its own API key or they'll have nonce conflicts and both will fail to trade. Create separate API keys for master and each user.

---

## Summary Checklist

Before submitting an issue, verify:

- [ ] I created a NEW API key on Kraken (not reusing existing)
- [ ] I enabled all required permissions (Query Funds, Orders, etc.)
- [ ] I set `KRAKEN_MASTER_API_KEY` in Railway/Render
- [ ] I set `KRAKEN_MASTER_API_SECRET` in Railway/Render
- [ ] I verified variable names are spelled correctly
- [ ] I verified there are no extra spaces/newlines in values
- [ ] I restarted the deployment after adding variables
- [ ] I checked logs for success/error messages
- [ ] I ran `python3 quick_fix_master_kraken.py` diagnostic

---

## Additional Resources

- **Diagnostic Script**: `quick_fix_master_kraken.py`
- **Detailed Troubleshooting**: `KRAKEN_MASTER_NOT_CONNECTING_JAN_16_2026.md`
- **Kraken Setup Guide**: `KRAKEN_QUICK_START.md`
- **Multi-Exchange Guide**: `MULTI_EXCHANGE_TRADING_GUIDE.md`
- **User Setup Guide**: `USER_SETUP_GUIDE.md`

---

## Still Need Help?

If you've followed all steps and master Kraken still won't connect:

1. Run the diagnostic and save the output:
   ```bash
   python3 quick_fix_master_kraken.py > diagnostic_output.txt
   ```

2. Check your deployment logs and copy any error messages

3. Create a GitHub issue with:
   - The diagnostic output
   - Any error messages from logs
   - Which deployment platform you're using (Railway/Render)
   - Confirmation that you followed all checklist items above

---

**Last Updated**: January 16, 2026  
**Issue**: Master Kraken not trading while users can trade on Kraken  
**Root Cause**: Master credentials not set in deployment environment  
**Fix Time**: 5-10 minutes  
**Difficulty**: Easy - just environment variable configuration
