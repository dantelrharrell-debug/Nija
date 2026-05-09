# Redis Connection Timeout Fix - Complete Diagnostic Guide

**Last Updated**: 2026-05-09  
**Current Status**: Bot crashing with Redis timeout at `viaduct.proxy.rlwy.net:20874`  
**Fix Deployed**: PR #1615 (graceful standby) - awaiting Railway redeploy

---

## 🔴 Current Error Pattern

```
⚠️ Redis connection attempt 1/5 failed: Timeout connecting to server
⚠️ Redis connection attempt 2/5 failed: Timeout connecting to server
⚠️ Redis connection attempt 3/5 failed: Timeout connecting to server
⚠️ Redis connection attempt 4/5 failed: Timeout connecting to server
❌ Redis connection failed after 5 attempts
❌ FAILED TO ACQUIRE WRITER LOCK
Exiting immediately due to NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS=true
❌ Bot crashed! Exit code: 1
```

---

## ✅ Immediate Action Plan

### Phase 1: Deploy Graceful Fallback (5 min)
**PR #1615 is merged but Railway hasn't deployed yet**

1. **Railway Dashboard** → NIJA service
2. Click **Redeploy** button (⟳ icon, top right)
3. Wait for deployment to complete (status shows checkmark)
4. Check logs for: `exit_on_unreachable_redis=False` ← indicates new code

### Phase 2: Fix Redis Connectivity (10-15 min)

---

## 🔍 Diagnostic Steps

### **Step 1: Verify Redis Service is Running**

**Location**: Railway Dashboard → Click "Redis" service

**Check**:
- [ ] Status indicator is 🟢 **Green** (Running)
- [ ] If 🔴 Red or 🟡 Yellow → Click **Restart**

**If Red after restart**: Redis has a crash/error
- Check Redis logs in Railway
- Look for memory issues or configuration errors

---

### **Step 2: Verify TCP Proxy is Enabled**

**Location**: Railway Dashboard → Redis service → **Networking** tab

**Check**:
- [ ] "Public Networking" or "TCP Proxy" section exists
- [ ] Status is "Enabled" (not "Disabled")
- [ ] Domain shows: `viaduct.proxy.rlwy.net` (or similar `.proxy.rlwy.net`)
- [ ] Port is a number (e.g., `20874`)

**If Disabled**:
1. Click **Enable** button
2. Wait 30-60 seconds for activation
3. Copy the new Domain and Port that appears

**If shows Domain + Port**: Copy both values
```
Domain: viaduct.proxy.rlwy.net
Port:   20874
```

---

### **Step 3: Get Redis Password**

**Location**: Railway Dashboard → Redis service → **Variables** tab

**Find**:
- [ ] `REDIS_PASSWORD` variable
- [ ] Copy the full value (including special characters)

**Example**:
```
REDIS_PASSWORD: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0
```

---

### **Step 4: Verify/Update NIJA_REDIS_URL**

**Location**: Railway Dashboard → NIJA service → **Variables** tab

**Current Value**: Should look like
```
NIJA_REDIS_URL=rediss://***@viaduct.proxy.rlwy.net:20874/0
```

**Correct Format**:
```
rediss://default:PASTE_PASSWORD_HERE@viaduct.proxy.rlwy.net:20874/0
```

**Replace**:
- `PASTE_PASSWORD_HERE` → copy from Redis REDIS_PASSWORD
- `viaduct.proxy.rlwy.net` → from Redis Networking Domain
- `20874` → from Redis Networking Port

**Example of correct URL**:
```
rediss://default:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0@viaduct.proxy.rlwy.net:20874/0
```

**CRITICAL**:
- ✅ Must use `rediss://` (with **"ss"**), NOT `redis://`
- ✅ Must include `/0` at end (database 0)
- ✅ No spaces around `@` or `:`

---

## 🧪 Test Redis Connection (Optional)

If you have a terminal with redis-cli:

```bash
redis-cli -h viaduct.proxy.rlwy.net \
  -p 20874 \
  -a "PASSWORD_HERE" \
  --tls \
  --insecure \
  ping
```

Expected response:
```
PONG
```

---

## 📋 Verification Checklist

Before redeploying NIJA:

- [ ] Redis service shows 🟢 Running
- [ ] TCP Proxy is Enabled with Domain + Port visible
- [ ] `NIJA_REDIS_URL` updated with correct connection string
- [ ] Connection string starts with `rediss://` (double s)
- [ ] Connection string ends with `/0`
- [ ] Password copied without extra spaces/quotes

---

## 🚀 Final Redeploy

1. **NIJA service** → **Redeploy** button
2. Wait for status checkmark
3. Check logs for:
   ```
   ✅ Distributed writer lock acquired
   ```

---

## 🎯 Expected Behavior After Fix

### Scenario A: Redis Recovers During Startup
```
⚠️  Redis preflight degraded (python ping failed)
STEP 1: imports done
STEP 2: loading bot.py...
🔄 Retrying distributed writer lock acquisition...
✅ Distributed writer lock acquired
🚀 Bot starting trading cycles...
```

### Scenario B: Redis Still Unreachable (Graceful Standby)
```
⚠️  Redis preflight degraded (python ping failed)
🛑 FAIL-CLOSED STANDBY ACTIVE: trading remains blocked until writer lock is acquired.
   Retrying distributed lock acquisition every 5s until acquired
⏳ Waiting for Redis lock...
⏳ Waiting for Redis lock...  ← repeats every 5s
[when Redis recovers]
✅ Distributed writer lock recovered; leaving fail-closed standby.
🚀 Bot starting trading cycles...
```

---

## 🆘 Troubleshooting

### "Redis connection still times out after all steps"
1. Check Railway Network tab for any IP blocking
2. Verify no firewall rules blocking viaduct.proxy.rlwy.net:20874
3. Try disabling and re-enabling TCP Proxy
4. Restart Redis service

### "NIJA_REDIS_URL keeps reverting"
1. Railway sometimes auto-detects URLs - check REDIS_TLS_URL or REDIS_URL
2. Set all competing variables to empty string:
   - `REDIS_URL =`
   - `REDIS_PRIVATE_URL =`
   - `REDIS_TLS_URL =`
3. Only keep `NIJA_REDIS_URL` populated

### "Still crashing even after PR deployment"
1. Force full redeploy: Delete old deployment → redeploy
2. Check git log: ensure latest commit is in Railway
3. Verify Railway using main branch (or correct branch)

---

## 📞 When All Else Fails

If Redis still won't connect:
1. **Temporarily disable lock** (unsafe, single-instance only):
   ```
   NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true
   ```
2. Redeploy with this set
3. Bot will trade without Redis lock protection
4. Fix Redis connectivity separately
5. Re-enable lock protection

---

**Document Version**: 1.0  
**Last Verified**: 2026-05-09 15:00 UTC
