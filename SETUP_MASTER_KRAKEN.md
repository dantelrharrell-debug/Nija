# Quick Guide: Connect Master Kraken Account

**Status**: You have successfully configured User #1 (Daivon) and User #2 (Tania) on Kraken, plus OKX master account. Now you just need to add the **Master Kraken credentials** to complete the setup.

---

## 🎯 What You Need

You need to add **2 environment variables** to your deployment:

```
KRAKEN_MASTER_API_KEY=your-kraken-api-key
KRAKEN_MASTER_API_SECRET=your-kraken-private-key
```

---

## 🚀 Quick Setup (Railway)

1. Go to https://railway.app/
2. Open your NIJA project
3. Click your service → **Variables** tab
4. Add these two variables:

   ```
   KRAKEN_MASTER_API_KEY → [your API key]
   KRAKEN_MASTER_API_SECRET → [your API secret]
   ```

5. Railway auto-restarts → Wait 2-3 minutes
6. Done! ✅

---

## 🚀 Quick Setup (Render)

1. Go to https://dashboard.render.com/
2. Select your NIJA service
3. Click **Environment** tab (left sidebar)
4. Add these two variables:

   ```
   KRAKEN_MASTER_API_KEY → [your API key]
   KRAKEN_MASTER_API_SECRET → [your API secret]
   ```

5. Click **Save Changes**
6. Click **Manual Deploy** → **Deploy latest commit**
7. Wait 3-5 minutes
8. Done! ✅

---

## 🔑 Get Your Kraken API Credentials

Don't have API credentials yet? Here's how to get them:

### Step 1: Create API Key on Kraken

1. Log in to https://www.kraken.com
2. Navigate to: **Settings → API → Create API Key**

### Step 2: Set Permissions

Enable these permissions (required for trading):

- ✅ **Query Funds**
- ✅ **Query Open Orders & Trades**
- ✅ **Query Closed Orders & Trades**
- ✅ **Create & Modify Orders**
- ✅ **Cancel/Close Orders**

### Step 3: Generate and Save

1. Name it: `NIJA Master Trading Bot`
2. Click **Generate Key**
3. **IMPORTANT**: Copy both **API Key** and **Private Key** immediately
   - You won't see the Private Key again!
4. Store them securely (use a password manager)

### Step 4: Add to Deployment

Use the Railway or Render instructions above to add the credentials.

---

## ✅ Verify It Worked

After deployment restarts, check your logs. You should see:

```
🔍 EXCHANGE CREDENTIAL STATUS:
   📊 KRAKEN (Master):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)   <- This should be ✅ now
   👤 KRAKEN (User #1: Daivon):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   👤 KRAKEN (User #2: Tania):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   📊 OKX (Master):
      ✅ Configured (Key: 36 chars, Secret: 32 chars)
```

Later in the logs:

```
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Connected to Kraken Pro API (MASTER)
   💰 Kraken balance: $X,XXX.XX
```

If all shows ✅, you're done! 🎉

---

## 🔧 Troubleshooting

### Still shows "Not configured" after restart

**Fix**:
1. Check variable names are **exactly** (case-sensitive):
   - `KRAKEN_MASTER_API_KEY` (not `kraken_master_api_key`)
   - `KRAKEN_MASTER_API_SECRET` (not `KRAKEN_MASTER_SECRET`)
2. Remove any spaces before/after the value
3. Make sure you added them to the correct service/project
4. Try deleting and re-adding the variables

### Shows "Invalid API key" or "Authentication failed"

This means credentials ARE loaded but are wrong:

**Fix**:
1. Double-check you copied the correct values from Kraken
2. Make sure API key permissions are enabled
3. Verify API key is not expired
4. Try regenerating a new API key on Kraken

### Connection timeout or network errors

**Fix**:
1. Check Kraken API status: https://status.kraken.com/
2. Verify your IP isn't blocked (if you set IP restrictions)
3. Check deployment platform network status

---

## 📋 Quick Reference Commands

If running locally:

```bash
# Check Kraken status
python3 check_kraken_status.py

# Diagnose connection issues
python3 diagnose_kraken_connection.py

# Interactive setup guide
python3 setup_kraken_master.py

# Check all environment variables
python3 diagnose_env_vars.py
```

---

## 🔒 Security Checklist

Before you add credentials:

- ✅ Never share API keys publicly
- ✅ Never commit to git
- ✅ Enable 2FA on Kraken account
- ✅ Use IP whitelist if possible
- ✅ Only enable needed permissions
- ✅ Store in password manager
- ✅ Rotate keys every 3-6 months

---

## 📚 Related Documentation

- **KRAKEN_SETUP_GUIDE.md** - Full Kraken setup guide
- **MULTI_USER_SETUP_GUIDE.md** - Managing multiple accounts
- **KRAKEN_RAILWAY_RENDER_SETUP.md** - Deployment-specific setup
- **SOLUTION_ENABLE_EXCHANGES.md** - Enable all exchanges
- **.env.example** - Local development template

---

## Summary

**Current Status**:
- ✅ Kraken User #1 (Daivon) - Configured
- ✅ Kraken User #2 (Tania) - Configured
- ✅ OKX Master - Configured
- ❌ **Kraken Master** - **Need to add**

**What to Do**:
1. Get Kraken API credentials (or use existing)
2. Add to Railway/Render: `KRAKEN_MASTER_API_KEY` + `KRAKEN_MASTER_API_SECRET`
3. Wait for restart
4. Verify in logs

**Time Required**: ~5 minutes (if you already have API keys)

---

**Last Updated**: January 13, 2026  
**Status**: Quick Reference Guide  
**Next Step**: Add credentials to Railway/Render
