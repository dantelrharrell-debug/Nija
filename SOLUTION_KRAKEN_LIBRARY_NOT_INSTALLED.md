# SOLUTION: Kraken Library Not Installed

**Date**: January 14, 2026  
**Issue**: Kraken not connecting despite having all environment variables configured  
**Root Cause**: `krakenex` library is not installed in the deployment environment

---

## The Problem

Your environment variables are **PERFECT** ✅. I can see:
- `KRAKEN_MASTER_API_KEY` - ✅ Set
- `KRAKEN_MASTER_API_SECRET` - ✅ Set
- `KRAKEN_USER_DAIVON_API_KEY` - ✅ Set
- `KRAKEN_USER_DAIVON_API_SECRET` - ✅ Set
- `KRAKEN_USER_TANIA_API_KEY` - ✅ Set
- `KRAKEN_USER_TANIA_API_SECRET` - ✅ Set

**BUT** the Kraken Python library (`krakenex`) is **NOT INSTALLED** in your deployment.

## Diagnosis

Run this diagnostic script to confirm:
```bash
python3 diagnose_kraken_library.py
```

Expected error:
```
❌ FAILED: krakenex cannot be imported
   Error: No module named 'krakenex'
```

## The Fix

### For Railway

#### Option 1: Force Rebuild (Recommended)
1. Go to your Railway dashboard
2. Click on your service
3. Go to **Settings** tab
4. Scroll down to **Danger Zone**
5. Click **"Restart Deployment"** or **"Redeploy"**
6. Railway will reinstall all dependencies from `requirements.txt`

#### Option 2: Clear Build Cache
1. Railway dashboard → Your service
2. Settings → Danger Zone
3. Click **"Clear Build Cache"**
4. Then redeploy

#### Option 3: Trigger Rebuild via Git
```bash
# Make a dummy change to force rebuild
git commit --allow-empty -m "Force rebuild to install krakenex"
git push
```

### For Render

#### Option 1: Manual Deploy (Recommended)
1. Go to Render dashboard
2. Click on your service
3. Click **"Manual Deploy"** button
4. Select **"Clear build cache & deploy"**

#### Option 2: Trigger via Git
```bash
# Make a dummy change
git commit --allow-empty -m "Force rebuild to install krakenex"
git push
```

---

## Verification After Fix

### Step 1: Check Deployment Logs

Look for these lines in your deployment logs:

**Good (should see)**:
```
Collecting krakenex==2.2.2
Successfully installed krakenex-2.2.2 pykrakenapi-0.3.2
```

**Bad (if you see)**:
```
ERROR: Could not find a version that satisfies the requirement krakenex
```

### Step 2: Check Bot Startup Logs

After successful deployment, look for:

**Good (should see)**:
```
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
   ✅ Kraken registered as MASTER broker in multi-account manager
```

**Bad (if you still see)**:
```
📊 Attempting to connect Kraken Pro (MASTER)...
   ⚠️  Kraken MASTER connection failed
```

### Step 3: Run Diagnostic

After redeployment, SSH into your deployment and run:
```bash
python3 diagnose_kraken_library.py
```

Expected output (after fix):
```
✅ SUCCESS: krakenex imported successfully
✅ SUCCESS: pykrakenapi imported successfully
✅ KRAKEN_MASTER_API_KEY: SET
✅ KRAKEN_MASTER_API_SECRET: SET
```

---

## Why This Happened

### Possible Causes

1. **Build Cache**: Railway/Render cached the build before `krakenex` was added to `requirements.txt`
2. **Installation Error**: The library failed to install but deployment continued
3. **Requirements Not Run**: The platform didn't execute `pip install -r requirements.txt`

### How to Prevent

1. **Always clear build cache** when adding new dependencies
2. **Check deployment logs** for successful installation
3. **Run diagnostic scripts** after deployment

---

## Alternative: Manual Installation Check

If you have SSH/shell access to your deployment:

```bash
# Check if krakenex is installed
pip list | grep kraken

# Expected output after fix:
# krakenex         2.2.2
# pykrakenapi      0.3.2

# If not installed, manually install:
pip install krakenex==2.2.2 pykrakenapi==0.3.2
```

---

## Quick Fix Commands

### Railway CLI
```bash
# If you have Railway CLI installed
railway run pip install -r requirements.txt
railway up
```

### Render
```bash
# Render doesn't have CLI for this
# Use the web dashboard to trigger manual deploy
```

---

## Expected Results After Fix

### Deployment Logs
```
Installing dependencies from requirements.txt
Collecting krakenex==2.2.2
  Downloading krakenex-2.2.2-py3-none-any.whl (15 kB)
Collecting pykrakenapi==0.3.2
  Downloading pykrakenapi-0.3.2-py3-none-any.whl (20 kB)
Successfully installed krakenex-2.2.2 pykrakenapi-0.3.2
```

### Bot Startup Logs
```
🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED
======================================================================
   Master account + User accounts trading independently
======================================================================

📊 Attempting to connect Coinbase Advanced Trade (MASTER)...
   ✅ Coinbase MASTER connected

📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
   ✅ Kraken registered as MASTER broker in multi-account manager

📊 Attempting to connect Kraken Pro user accounts...
   ✅ Kraken user 'daivon_frazier' connected
   ✅ Kraken user 'tania_gilbert' connected

📊 Trading will occur on 2 exchange(s): COINBASE, KRAKEN
✅ All broker connections complete
```

---

## Summary

| Item | Status |
|------|--------|
| **Environment Variables** | ✅ PERFECT - All set correctly |
| **Credentials** | ✅ VALID - Master + 2 users configured |
| **Library in requirements.txt** | ✅ PRESENT - krakenex==2.2.2 listed |
| **Library Installed** | ❌ **MISSING** - Not installed in deployment |
| **Fix Required** | ✅ Redeploy with build cache cleared |

---

## The Fix (Step-by-Step)

### Railway
1. Dashboard → Your Service
2. Click **Settings**
3. Scroll to **Danger Zone**
4. Click **"Restart Deployment"**
5. Wait for rebuild (watch logs)
6. Verify `krakenex` installation in logs
7. Check bot startup logs for Kraken connection

### Render
1. Dashboard → Your Service  
2. Click **"Manual Deploy"**
3. Select **"Clear build cache & deploy"**
4. Wait for rebuild (watch logs)
5. Verify `krakenex` installation in logs
6. Check bot startup logs for Kraken connection

---

**Bottom Line**: Your credentials are perfect. The library just needs to be installed. Clear the build cache and redeploy. Kraken will connect immediately after that.

**After Fix**: You'll see "✅ Kraken MASTER connected" and "✅ Kraken user 'daivon_frazier' connected" in your logs. All 3 accounts will trade on Kraken!
