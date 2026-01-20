# B) KRAKEN PERSISTENT NONCE - RAILWAY DEPLOYMENT GUIDE

**Date:** January 20, 2026  
**Platform:** Railway (https://railway.app)  
**Status:** ✅ PRODUCTION-READY

---

## Executive Summary

This guide provides step-by-step instructions for deploying the Global Kraken Nonce Manager to Railway. The implementation ensures nonce persistence across Railway's ephemeral container restarts and provides guaranteed collision-free operation for MASTER + ALL USER accounts.

---

## Why Railway Needs Special Configuration

### Railway Container Characteristics

- **Ephemeral filesystem** - Files written to disk are lost on restart
- **Automatic restarts** - Service restarts on deploy, crash, or platform maintenance
- **No local state** - Cannot rely on in-memory or file-based state
- **Volume support** - Persistent storage available via Railway Volumes

### The Nonce Persistence Problem

Without persistent storage, the Global Kraken Nonce Manager will:
1. Start with `time.time_ns()` on each restart
2. Potentially reuse nonces from previous session
3. Cause "Invalid nonce" errors from Kraken API
4. Break trading execution

**Solution:** Use Railway Volumes to persist `data/kraken_global_nonce.txt`

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Railway Container (Ephemeral)                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  /app/                     (Ephemeral - Code)       │
│  /app/bot/                 (Ephemeral - Source)     │
│  /app/data/ ─────────┐                              │
│                      │                               │
│                      └──> MOUNT POINT                │
│                           ↓                          │
│                      Railway Volume                  │
│                      (PERSISTENT)                    │
│                      /data/kraken_global_nonce.txt   │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## Step-by-Step Railway Setup

### Step 1: Create Railway Project

1. **Sign in to Railway**
   - Go to https://railway.app
   - Sign in with GitHub

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your `Nija` repository
   - Railway will auto-detect `Dockerfile` or use `Procfile`

3. **Initial Deploy**
   - Let Railway complete the initial deployment
   - This creates the base service (may fail - that's OK)

### Step 2: Add Persistent Volume

1. **Open Project Settings**
   - Click on your Railway project
   - Click on the service (bot container)
   - Go to "Settings" tab

2. **Create Volume**
   - Scroll to "Volumes" section
   - Click "+ New Volume"
   - **Volume Name:** `nija-data`
   - **Mount Path:** `/app/data`
   - Click "Add"

3. **Verify Volume**
   - Volume should appear in settings
   - Mount path: `/app/data`
   - Status: Active

### Step 3: Configure Environment Variables

1. **Add Required Variables**
   
   Navigate to "Variables" tab and add:

   ```bash
   # Kraken Master Credentials
   KRAKEN_API_KEY=<your_kraken_api_key>
   KRAKEN_API_SECRET=<your_kraken_api_secret>
   
   # Kraken User Credentials (if multi-user)
   KRAKEN_USER_daivon_frazier_API_KEY=<api_key>
   KRAKEN_USER_daivon_frazier_API_SECRET=<api_secret>
   
   # Coinbase Credentials
   COINBASE_API_KEY=<your_coinbase_api_key>
   COINBASE_API_SECRET=<your_coinbase_api_secret>
   COINBASE_PEM_CONTENT=<your_pem_content>
   
   # Data Directory (must match volume mount)
   DATA_DIR=/app/data
   
   # Optional: Trading Parameters
   HARD_BUY_OFF=0
   ```

2. **Verify Volume Mount**
   
   The `DATA_DIR` environment variable MUST match the volume mount path.
   
   - Volume mount: `/app/data`
   - Environment: `DATA_DIR=/app/data`

### Step 4: Update Code for Railway

**File:** `bot/global_kraken_nonce.py`

Ensure the data directory uses the environment variable:

```python
# At the top of bot/global_kraken_nonce.py
import os

# Data directory - Railway uses /app/data (mounted volume)
_data_dir = os.getenv('DATA_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))

# Ensure directory exists
os.makedirs(_data_dir, exist_ok=True)
```

**File:** `railway.json` (create if not exists)

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "bash start.sh",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### Step 5: Update Dockerfile

Ensure `Dockerfile` creates the data directory:

```dockerfile
# ... existing Dockerfile content ...

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Railway will mount volume at /app/data

# ... rest of Dockerfile ...
```

### Step 6: Deploy to Railway

1. **Commit Changes**
   ```bash
   git add railway.json Dockerfile bot/global_kraken_nonce.py
   git commit -m "Configure Railway persistent volume for Kraken nonce"
   git push origin main
   ```

2. **Railway Auto-Deploy**
   - Railway detects the push and starts deployment
   - Watch the build logs in Railway dashboard
   - Verify container starts successfully

3. **Verify Nonce Persistence**
   
   Check logs for initialization:
   ```
   Global Kraken Nonce Manager initialized (persisted nonce: XXXXX, API serialization: ENABLED)
   ```
   
   OR if first run:
   ```
   No persisted nonce found, initializing with current time: XXXXX
   ```

### Step 7: Test Nonce Persistence

1. **Generate Some Nonces**
   - Let the bot run for a few minutes
   - Make some Kraken API calls
   - Watch for successful balance checks

2. **Force Restart**
   - In Railway dashboard, click "Restart"
   - Watch logs during restart

3. **Verify Nonce Loading**
   
   Look for this in logs:
   ```
   Loaded persisted nonce: 1737159471234567890, using: 1737159471234567891
   ```
   
   The "using" value should be HIGHER than the "persisted" value.

4. **Verify No Nonce Errors**
   
   You should NOT see:
   ```
   ❌ Kraken API error: EAPI:Invalid nonce
   ```

---

## Troubleshooting

### Issue 1: "Invalid nonce" Errors After Restart

**Symptom:**
```
❌ Kraken API error: EAPI:Invalid nonce
```

**Cause:** Nonce file not persisting across restarts

**Solution:**

1. Verify volume is mounted:
   ```bash
   # SSH into Railway container (if available)
   ls -la /app/data/
   # Should show: kraken_global_nonce.txt
   ```

2. Check environment variable:
   ```bash
   echo $DATA_DIR
   # Should output: /app/data
   ```

3. Check file permissions:
   ```bash
   ls -la /app/data/kraken_global_nonce.txt
   # Should be writable by app user
   ```

4. If file missing, check logs for write errors:
   ```bash
   grep "Could not persist nonce" <logs>
   ```

### Issue 2: Volume Not Mounting

**Symptom:**
```
Could not persist nonce to disk: [Errno 2] No such file or directory: '/app/data/kraken_global_nonce.txt'
```

**Cause:** Volume not properly configured in Railway

**Solution:**

1. Go to Railway dashboard → Service → Settings → Volumes
2. Verify volume exists with mount path `/app/data`
3. If missing, create volume (see Step 2)
4. Redeploy service

### Issue 3: Nonce File Permissions Error

**Symptom:**
```
Could not persist nonce to disk: [Errno 13] Permission denied: '/app/data/kraken_global_nonce.txt'
```

**Cause:** Container user doesn't have write permission

**Solution:**

Update `Dockerfile` to fix permissions:

```dockerfile
# Create data directory with proper permissions
RUN mkdir -p /app/data && chmod 777 /app/data

# OR if using a specific user:
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data
```

### Issue 4: Nonce Resets to Current Time

**Symptom:** Nonce always starts from current time after restart

**Cause:** Persistence file not being read

**Solution:**

1. Check if file exists:
   ```python
   import os
   print(f"File exists: {os.path.exists('/app/data/kraken_global_nonce.txt')}")
   ```

2. Check file content:
   ```bash
   cat /app/data/kraken_global_nonce.txt
   # Should show a 19-digit number
   ```

3. Check logs for load errors:
   ```
   Could not load persisted nonce: <error>
   ```

---

## Monitoring

### Key Log Patterns

#### ✅ Healthy Operation

```
Global Kraken Nonce Manager initialized (persisted nonce: 1737159471234567890, API serialization: ENABLED)
✅ Using GLOBAL Kraken Nonce Manager for MASTER (nanosecond precision)
Loaded persisted nonce: 1737159471234567890, using: 1737159471234567891
💰 Kraken Balance (MASTER): ✅ Available USD: $1234.56
```

#### ⚠️ Warning Signs

```
No persisted nonce found, initializing with current time: <timestamp>
Could not persist nonce to disk: <error>
⚠️ Global nonce manager not available, falling back to per-user KrakenNonce
```

#### 🛑 Critical Issues

```
❌ Kraken API error: EAPI:Invalid nonce
❌ Kraken marked unavailable after 3 consecutive errors
Could not load persisted nonce: [Errno 2] No such file or directory
```

### Railway Monitoring

1. **Check Nonce File**
   
   Add a health check endpoint:
   ```python
   from flask import jsonify
   from bot.global_kraken_nonce import get_global_nonce_stats
   
   @app.route('/health/kraken-nonce')
   def kraken_nonce_health():
       stats = get_global_nonce_stats()
       return jsonify({
           'status': 'healthy',
           'last_nonce': stats['last_nonce'],
           'total_issued': stats['total_nonces_issued'],
           'uptime': stats['uptime_seconds'],
           'api_serialization': stats['api_serialization_enabled']
       })
   ```

2. **Railway Logs**
   
   Filter logs for nonce-related events:
   ```
   View logs → Filter by text:
   - "Global Kraken Nonce"
   - "Invalid nonce"
   - "persisted nonce"
   ```

3. **Metrics to Track**
   
   - Nonce persistence file age (should update frequently)
   - Last nonce value (should increase monotonically)
   - Kraken API error rate (should be near zero)
   - Total nonces issued (should increase over time)

---

## Alternative: Environment Variable Storage

If Railway Volumes are not available or not working, use environment variables as a backup:

### Implementation

**File:** `bot/global_kraken_nonce.py`

```python
def _load_nonce_from_disk(self) -> int:
    """
    Load the last nonce from disk or environment variable.
    
    Order of precedence:
    1. Disk file (if available)
    2. KRAKEN_LAST_NONCE environment variable
    3. Current timestamp (fallback)
    """
    current_time_ns = time.time_ns()
    
    # Try disk first
    if os.path.exists(self._nonce_file):
        try:
            with open(self._nonce_file, 'r') as f:
                content = f.read().strip()
                if content:
                    persisted_nonce = int(content)
                    initial_nonce = max(persisted_nonce + 1, current_time_ns)
                    logger.info(f"Loaded persisted nonce from disk: {persisted_nonce}, using: {initial_nonce}")
                    return initial_nonce
        except (ValueError, IOError) as e:
            logger.warning(f"Could not load persisted nonce from disk: {e}")
    
    # Try environment variable
    env_nonce = os.getenv('KRAKEN_LAST_NONCE')
    if env_nonce:
        try:
            persisted_nonce = int(env_nonce)
            initial_nonce = max(persisted_nonce + 1, current_time_ns)
            logger.info(f"Loaded persisted nonce from ENV: {persisted_nonce}, using: {initial_nonce}")
            return initial_nonce
        except ValueError as e:
            logger.warning(f"Could not parse KRAKEN_LAST_NONCE from ENV: {e}")
    
    # Fallback to current time
    logger.info(f"No persisted nonce found, initializing with current time: {current_time_ns}")
    return current_time_ns

def _persist_nonce_to_disk(self, nonce: int):
    """
    Persist the nonce to disk AND environment variable.
    """
    # Try disk
    try:
        with open(self._nonce_file, 'w') as f:
            f.write(str(nonce))
    except IOError as e:
        logger.debug(f"Could not persist nonce to disk: {e}")
    
    # Try environment (for next restart)
    # Note: This only works if Railway picks up environment changes
    # Manual update required in Railway dashboard
    try:
        os.environ['KRAKEN_LAST_NONCE'] = str(nonce)
    except Exception as e:
        logger.debug(f"Could not persist nonce to ENV: {e}")
```

### Manual Environment Update

After each Railway restart, manually update:
```bash
# In Railway dashboard → Variables
KRAKEN_LAST_NONCE=<last_nonce_from_logs>
```

**Note:** This is NOT automatic and requires manual intervention. Use volumes instead.

---

## Summary

### Railway Configuration Checklist

- [x] Railway project created from GitHub repo
- [x] Persistent volume added (`nija-data` at `/app/data`)
- [x] Environment variable `DATA_DIR=/app/data` configured
- [x] Dockerfile creates `/app/data` directory
- [x] `railway.json` specifies start command
- [x] Code uses `DATA_DIR` environment variable
- [x] Volume mount verified in Railway dashboard
- [x] Initial deployment successful
- [x] Nonce persistence verified after restart
- [x] No "Invalid nonce" errors in logs
- [x] Monitoring/health checks added

### Key Files

- `bot/global_kraken_nonce.py` - Global nonce manager
- `railway.json` - Railway configuration
- `Dockerfile` - Container setup
- `/app/data/kraken_global_nonce.txt` - Persistent nonce file (on volume)

### Railway Variables

```bash
DATA_DIR=/app/data
KRAKEN_API_KEY=<key>
KRAKEN_API_SECRET=<secret>
COINBASE_API_KEY=<key>
COINBASE_API_SECRET=<secret>
COINBASE_PEM_CONTENT=<pem>
```

### Success Criteria

✅ Nonce file persists across Railway restarts  
✅ No "Invalid nonce" errors from Kraken API  
✅ Logs show "Loaded persisted nonce" on startup  
✅ All Kraken accounts use global nonce manager  
✅ API serialization enabled and working

---

**Status:** ✅ PRODUCTION-READY  
**Platform:** Railway  
**Last Updated:** January 20, 2026
