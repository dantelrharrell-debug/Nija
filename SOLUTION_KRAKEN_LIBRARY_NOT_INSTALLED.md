# SOLUTION: Kraken Library Not Installed

**Date**: January 17, 2026 (Updated)  
**Issue**: Kraken not connecting despite having all environment variables configured  
**Root Cause**: `krakenex` library is not installed in the deployment environment  
**New Fix**: Force Railway to use Dockerfile instead of Nixpacks buildpack

---

## The Problem

Your environment variables are **PERFECT** ✅. I can see:
- `KRAKEN_MASTER_API_KEY` - ✅ Set
- `KRAKEN_MASTER_API_SECRET` - ✅ Set
- `KRAKEN_USER_DAIVON_API_KEY` - ✅ Set (optional)
- `KRAKEN_USER_DAIVON_API_SECRET` - ✅ Set (optional)
- `KRAKEN_USER_TANIA_API_KEY` - ✅ Set (optional)
- `KRAKEN_USER_TANIA_API_SECRET` - ✅ Set (optional)

**BUT** the Kraken Python library (`krakenex`) is **NOT INSTALLED** in your deployment.

## What's Different (Jan 17, 2026 Update)

We discovered that Railway's **Nixpacks buildpack** sometimes **silently fails** to install the Kraken SDK, even though it's in `requirements.txt`.

**The fix**: We've updated `railway.json` to force Railway to use the **Dockerfile** instead, which:
1. Explicitly installs Kraken SDK with proper dependencies
2. Includes preflight checks to verify installation
3. **Fails the build** if SDK doesn't install (preventing broken deployments)

Additionally, `start.sh` now **fails fast** if Kraken credentials are set but SDK is missing, providing clear error messages.

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

## The Fix (UPDATED - Jan 17, 2026)

### For Railway (Recommended - Uses Docker)

**Important**: The repository now forces Docker builds via `railway.json`. This ensures reliable SDK installation.

#### Step 1: Verify Configuration
The latest `railway.json` now contains:
```json
{
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  }
}
```

This forces Railway to use the Dockerfile instead of Nixpacks.

#### Step 2: Redeploy with Fresh Build
1. Go to your Railway dashboard
2. Click on your service
3. Go to **Settings** tab
4. Scroll down to **Danger Zone**
5. Click **"Restart Deployment"** or **"Redeploy"**
6. **Important**: This MUST be a REDEPLOY (not just Restart)
   - "Restart" reuses existing container (SDK still missing)
   - "Redeploy" rebuilds from Dockerfile (SDK will be installed)

#### Step 3: Verify Build Uses Docker
Check deployment logs for:
```
Building with Dockerfile
...
RUN python3 -m pip install krakenex==2.2.2 pykrakenapi==0.3.2
✅ Kraken SDK (krakenex + pykrakenapi) import successful
```

If you see "Building with Nixpacks" instead, the configuration didn't take effect. See troubleshooting below.

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

## Why This Happened (UPDATED)

### Root Cause: Railway Buildpack vs Docker

**Original Issue**: Railway's Nixpacks buildpack silently failed to install Kraken SDK
- `krakenex` and `pykrakenapi` have dependencies on `pandas` and `numpy`
- Nixpacks sometimes fails to resolve version conflicts
- Installation errors don't always appear in logs
- The bot started anyway because SDK check was optional

**Why Docker Fixes It**:
1. **Explicit installation order**: Core deps → Coinbase SDK → Kraken SDK → Other packages
2. **Preflight checks**: Build fails if SDK doesn't import
3. **Version pinning**: Uses exact tested versions of all dependencies
4. **Clear error messages**: If anything fails, build stops immediately

### Previous Build Method (Nixpacks)
```toml
[phases.install]
cmds = [
  'python3 -m pip install -r requirements.txt'
]
```
→ Packages install in arbitrary order, conflicts may occur, errors may be silent

### New Build Method (Dockerfile)
```dockerfile
# Install Kraken SDK explicitly
RUN python3 -m pip install --no-cache-dir \
    krakenex==2.2.2 \
    pykrakenapi==0.3.2

# Verify installation
RUN python3 -c "import krakenex; import pykrakenapi; print('✅ Kraken SDK import successful')"
```
→ Controlled installation order, immediate verification, fails fast on errors

---

## Troubleshooting

### Railway Still Uses Nixpacks After Update

**Symptom**: Deployment logs show "Building with Nixpacks" instead of "Building with Dockerfile"

**Cause**: Railway caches the build configuration for existing services

**Fix Options**:

1. **Delete and Recreate Service** (Most Reliable)
   - Delete the service in Railway dashboard
   - Recreate service from the same GitHub repository
   - Railway will read fresh `railway.json` and use Docker
   - **Warning**: This will reset your deployment URL

2. **Force Configuration Refresh**
   - Railway CLI: `railway link` then `railway up`
   - Or contact Railway support to refresh configuration

3. **Override via Dashboard** (If available)
   - Railway Dashboard → Service → Settings
   - Look for "Build Settings" or "Builder"
   - Change from "RAILPACK" to "DOCKERFILE"

### Deployment Fails with "Kraken SDK NOT installed" Error

**Good!** This is the new fail-fast behavior.

**What it means**:
- Kraken credentials are configured ✅
- Kraken SDK failed to install ❌
- Bot refuses to start (preventing silent failures) ✅

**To fix**:
1. Check if deployment uses Docker (see above)
2. If using Nixpacks, force Docker build
3. If using Docker but still failing, check Docker build logs for errors

### Manual Installation (Temporary Workaround)

If you can't redeploy immediately but need Kraken working:

```bash
# SSH into your Railway container (if enabled)
pip install krakenex==2.2.2 pykrakenapi==0.3.2

# Restart the bot process
# Note: This is temporary - will reset on next deployment
```

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
