# NIJA Redis Lock Recovery Guide

## Current Status

Your NIJA bot is stuck in **fail-closed standby mode** waiting to acquire a distributed Redis lock. The container cannot connect to Redis at `maglev.proxy.rlwy.net:31245`.

**Logs show:**
```
⚠️ Redis connection attempt 1/5 failed: Timeout connecting to server
...
❌ Redis connection failed after 5 attempts
❌ FAILED TO ACQUIRE WRITER LOCK
🛑 FAIL-CLOSED STANDBY ACTIVE: trading remains blocked until writer lock is acquired
```

---

## 🔍 Quick Diagnosis

### Check 1: Is Redis Service Running?

1. Go to **Railway Dashboard** → Your project
2. Look for **Redis** service in the services list
3. Check its status indicator:
   - 🟢 **Green** = Running (go to Check 2)
   - 🔴 **Red** = Crashed/Offline (jump to **FIX #1** below)
   - 🟡 **Yellow** = Degraded (restart it)

### Check 2: Is TCP Proxy Enabled?

1. Click on the **Redis** service
2. Go to **Networking** tab
3. Look for "Public Networking" or "TCP Proxy":
   - ✅ **Enabled** → Shows Domain and Port (should be `maglev.proxy.rlwy.net:xxxxx`)
   - ❌ **Disabled** → Jump to **FIX #2** below

### Check 3: Is NIJA Environment Set Correctly?

1. Click on the **NIJA** service
2. Go to **Variables** tab
3. Look for `NIJA_REDIS_URL`:
   - Should look like: `rediss://default:PASSWORD@maglev.proxy.rlwy.net:PORT/0`
   - Must use **`rediss://`** (with "ss"), NOT `redis://`
   - Must include the **correct TCP proxy port** from Redis service

---

## 🔧 FIXES (Choose Based on Your Diagnosis)

### FIX #1: Redis Service is Offline

**Action:**
1. In Railway Dashboard → Click **Redis** service
2. Click **Restart** button (top right)
3. Wait 30-60 seconds for service to restart
4. Check status indicator turns 🟢 Green
5. Then restart **NIJA** service

**Why:** Redis may have crashed or hit memory limits. Restarting fixes 90% of lock issues.

---

### FIX #2: TCP Proxy is Disabled

**Action:**
1. In Railway Dashboard → Click **Redis** service
2. Click **Variables** tab
3. Note the `REDIS_PASSWORD` value (copy it)
4. Click **Networking** tab
5. Enable "Public Networking" or "TCP Proxy"
6. Wait for it to activate (shows Domain + Port)
7. Go to **NIJA** service → **Variables**
8. Update or create `NIJA_REDIS_URL`:
   ```
   rediss://default:YOUR_REDIS_PASSWORD@maglev.proxy.rlwy.net:PORT/0
   ```
   (Replace `YOUR_REDIS_PASSWORD` and `PORT` with actual values)
9. Restart **NIJA** service

**Why:** TCP proxy allows NIJA to connect to Redis from outside Railway's internal network.

---

### FIX #3: NIJA_REDIS_URL is Wrong or Missing

**Action:**
1. In Railway → **Redis** service → **Networking** tab
   - Copy the Domain (e.g., `maglev.proxy.rlwy.net`)
   - Copy the Port (e.g., `31245`)
2. In Railway → **Redis** service → **Variables** tab
   - Find `REDIS_PASSWORD` and copy the value
3. In Railway → **NIJA** service → **Variables** tab
4. Find or create `NIJA_REDIS_URL`:
   ```
   rediss://default:YOUR_PASSWORD_HERE@maglev.proxy.rlwy.net:YOUR_PORT/0
   ```

**Example:**
```
NIJA_REDIS_URL=rediss://default:2eF9xK_3mL#pQ@maglev.proxy.rlwy.net:31245/0
```

5. Restart **NIJA** service

---

### FIX #4: Network Connectivity Issue (Advanced)

If Redis service is 🟢 online and TCP proxy is ✅ enabled but still timing out:

**Test from NIJA container:**
1. In Railway → **NIJA** service → **Logs** tab
2. Look for any error patterns
3. Test connectivity manually:
   ```bash
   # Inside your container or local machine:
   redis-cli -h maglev.proxy.rlwy.net -p 31245 \
     -a your_password \
     --tls --insecure ping
   ```

**If that fails:**
- Try with `--tls --insecure-skip-verify`
- Check if port is correct (should NOT be 6379 for TCP proxy)
- Verify password doesn't have special characters that need escaping

---

## ⚡ EMERGENCY BYPASS (Last Resort Only)

**Use this ONLY if:**
- You need to trade immediately
- Redis recovery will take time
- You have exactly **1 replica** of NIJA running

**Action:**
1. In Railway → **NIJA** service → **Variables** tab
2. Create new variable:
   ```
   NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true
   ```
3. Restart **NIJA** service

**⚠️ WARNING:**
- This disables the single-writer lock protection
- If you accidentally run 2 NIJA instances with this enabled, **data corruption will occur**
- Only safe with exactly 1 replica
- Disable this immediately once Redis recovers

**To disable:**
1. Remove or set to `false`:
   ```
   NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=false
   ```
2. Restart **NIJA** service

---

## 🔄 Clear Stale Locks (If Lock Persists After Redis Returns)

If Redis comes back online but NIJA still can't acquire the lock:

```bash
# From your local machine or container:
python scripts/clear_redis_locks.py --clear
```

This deletes any stale lock entries.

---

## ✅ Verification Checklist

After applying a fix, verify with this checklist:

- [ ] Redis service shows 🟢 Green status in Railway
- [ ] Redis service **Networking** shows TCP Proxy enabled
- [ ] NIJA service has `NIJA_REDIS_URL` set (or similar)
- [ ] URL format is `rediss://default:PASSWORD@HOST:PORT/0`
- [ ] NIJA service is restarted
- [ ] Check NIJA logs for: `✅ Distributed writer lock ready` or similar

---

## 📊 Expected Behavior

### Before Fix
```
⚠️ Redis connection attempt 1/5 failed: Timeout connecting to server
⚠️ Redis connection attempt 2/5 failed: Timeout connecting to server
...
❌ FAILED TO ACQUIRE WRITER LOCK
🛑 FAIL-CLOSED STANDBY ACTIVE: trading remains blocked
```

### After Fix
```
✅ Redis connection established
✅ Distributed writer lock acquired
✅ Live trading approved: LIVE_CAPITAL_VERIFIED=true
🔥 Starting live trading bot...
```

---

## 🆘 If You're Still Stuck

1. **Gather diagnostics:**
   ```bash
   # From NIJA container or locally:
   python scripts/diagnose_and_fix_redis_lock.py
   ```

2. **Check logs for pattern:**
   - "Timeout" = Network/DNS unreachable
   - "AUTH" or "password" = Wrong credentials
   - "MOVED" or "LOADING" = Redis cluster issue
   - "refused" = Port not listening

3. **Last resort - clear everything:**
   ```bash
   # Clear all NIJA Redis data (use with caution!)
   python scripts/clear_redis_locks.py --force
   ```

---

## 📚 Related Documentation

- [REDIS_RAILWAY_SETUP.md](../REDIS_RAILWAY_SETUP.md) - Detailed TCP proxy setup
- [PRODUCTION_REDIS_RESILIENCE_RUNBOOK.md](../PRODUCTION_REDIS_RESILIENCE_RUNBOOK.md) - Advanced troubleshooting
- Railway Docs: https://docs.railway.app/reference/environment-variables

---

## Key Environment Variables Reference

| Variable | Purpose | Example |
|----------|---------|---------|
| `NIJA_REDIS_URL` | Full Redis connection URL | `rediss://default:PWD@host:port/0` |
| `REDIS_PASSWORD` | Password for Redis auth | `2eF9xK_3mL#pQ` |
| `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK` | Emergency bypass (UNSAFE) | `true` / `false` |
| `NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE` | Keep retrying on lock error | `true` (default) |
| `NIJA_FAIL_CLOSED_RETRY_INTERVAL_S` | Seconds between lock retries | `5` (default) |

---

**Last Updated:** 2026-05-09  
**Status:** Fail-closed lock mode - awaiting Redis connectivity
