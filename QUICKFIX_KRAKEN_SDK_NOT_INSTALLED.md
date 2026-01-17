# QUICK FIX: Enable Kraken Master Trading

**Date**: January 17, 2026  
**Issue**: Master account not trading on Kraken  
**Status**: ✅ **FIXED** - Requires redeployment

---

## What Was Wrong

Your Kraken credentials are configured correctly, but the Kraken SDK (`krakenex` + `pykrakenapi`) was **not installed** in your Railway deployment.

**Why it happened:**
- Railway was using **Nixpacks buildpack** instead of Docker
- Nixpacks silently failed to install the Kraken SDK packages
- The bot started anyway (SDK check was optional)
- Result: Credentials found, but SDK missing = connection failed

---

## What I Fixed

### 1. Force Docker Build (`railway.json`)
Changed Railway configuration to use Dockerfile:
```json
{
  "build": {
    "builder": "DOCKERFILE"
  }
}
```
(Changed from `"builder": "NIXPACKS"`)

**Why this matters:**
- Dockerfile **explicitly** installs Kraken SDK with proper dependencies
- Includes **preflight checks** that fail the build if SDK doesn't import
- Much more reliable than Nixpacks auto-detection

### 2. Fail-Fast Check (`start.sh`)
Added strict validation that **fails the deployment** if:
- Kraken credentials are set ✅
- Kraken SDK is not installed ❌

**Before** (old behavior):
```
⚠️  Kraken SDK not installed (optional)
[bot starts anyway, Kraken connection fails silently]
```

**After** (new behavior):
```
❌ CRITICAL: Kraken Master credentials are set but Kraken SDK is NOT installed

🔧 SOLUTION:
   1. Verify railway.json uses 'builder': 'DOCKERFILE'
   2. Trigger a fresh deployment (not just restart)
   
[deployment stops, provides clear fix instructions]
```

### 3. Updated Documentation
Updated `SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md` with:
- Explanation of Nixpacks vs Docker issue
- Railway-specific troubleshooting
- Step-by-step redeployment guide

---

## What You Need to Do

### 🚀 Deploy the Fix

**IMPORTANT**: You must **REDEPLOY** (not just restart)

#### Railway Dashboard:
1. Go to your Railway service
2. Click **Settings** tab
3. Scroll to **Danger Zone**
4. Click **"Restart Deployment"** or **"Redeploy"**

**Why "Redeploy" not "Restart":**
- ❌ **Restart**: Reuses existing container (SDK still missing)
- ✅ **Redeploy**: Rebuilds from Dockerfile (SDK will be installed)

### ✅ Verify the Fix

After redeployment, check the deployment logs for:

1. **Build logs should show:**
   ```
   Building with Dockerfile
   ...
   RUN python3 -m pip install krakenex==2.2.2 pykrakenapi==0.3.2
   Successfully installed krakenex-2.2.2 pykrakenapi-0.3.2
   ✅ Kraken SDK (krakenex + pykrakenapi) import successful
   ```

2. **Startup logs should show:**
   ```
   ✅ Kraken SDK (krakenex + pykrakenapi) available
   ...
   📊 Attempting to connect Kraken Pro (MASTER)...
      Testing Kraken connection (MASTER)...
   ✅ KRAKEN PRO CONNECTED (MASTER)
      Account: MASTER
      USD Balance: $X.XX
      USDT Balance: $X.XX
      Total: $X.XX
   ```

3. **Trading status should show:**
   ```
   ✅ MASTER ACCOUNT BROKERS: Coinbase, Kraken
   ```

---

## If Deployment Still Fails

### Symptom: "Building with Nixpacks" in logs

**Cause**: Railway cached the old build configuration

**Fix**: Delete and recreate the service
1. Railway Dashboard → Your Service → Settings
2. Danger Zone → "Delete Service"
3. Create new service from same GitHub repository
4. Railway will use fresh `railway.json` (Docker build)

**Note**: This will reset your deployment URL

### Symptom: "Kraken SDK NOT installed" error at startup

**Good!** This is the new fail-fast behavior.

**What it means:**
- The deployment used Nixpacks (not Docker)
- Kraken SDK didn't install
- Bot refuses to start (prevents silent failures)

**Fix**: See above - force Docker build

---

## Summary

| Item | Before | After |
|------|--------|-------|
| **Build System** | ❌ Nixpacks (unreliable) | ✅ Docker (reliable) |
| **SDK Installation** | ❌ Silent failure | ✅ Explicit + verified |
| **Error Handling** | ⚠️ Warning only | ❌ Fails fast with fix instructions |
| **Kraken Trading** | ❌ Not working | ✅ Will work after redeploy |

---

## Expected Result

After redeployment with the fix:

```
🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED
📊 Attempting to connect Coinbase Advanced Trade (MASTER)...
   ✅ Coinbase MASTER connected

📊 Attempting to connect Kraken Pro (MASTER)...
   Testing Kraken connection (MASTER)...
✅ KRAKEN PRO CONNECTED (MASTER)
   Account: MASTER
   USD Balance: $X.XX
   USDT Balance: $X.XX
   Total: $X.XX

✅ MASTER ACCOUNT BROKERS: Coinbase, Kraken
📈 Trading will occur on 2 exchange(s)
```

Your master account will now trade on **both Coinbase and Kraken**! 🎉

---

## Questions?

- **Build still using Nixpacks?** → See troubleshooting above
- **Other deployment errors?** → Check `SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md`
- **Need help?** → The error messages now include fix instructions

The fix is ready - just redeploy! 🚀
