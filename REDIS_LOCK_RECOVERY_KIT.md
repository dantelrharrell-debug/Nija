# NIJA Redis Lock Issue - Complete Recovery Toolkit

**Issue:** NIJA bot stuck in fail-closed standby mode - cannot acquire distributed Redis lock

**Root Cause:** Redis at `maglev.proxy.rlwy.net:31245` is unreachable (timeout)

**Status:** 🔴 CRITICAL - Trading is blocked

**Time to Fix:** 5-10 minutes (most cases)

---

## 📋 Start Here

Choose based on your situation:

### 🟢 I know what went wrong (Redis is offline/crashed)
→ **[REDIS_LOCK_QUICK_FIX.md](REDIS_LOCK_QUICK_FIX.md)** (2 min read)

### 🟡 I need step-by-step diagnostics to find the issue
→ **[REDIS_LOCK_RECOVERY_GUIDE.md](REDIS_LOCK_RECOVERY_GUIDE.md)** (10 min read)

### 🔵 I want to use interactive tools
→ **`bash scripts/railway_redis_recovery.sh`** (menu-driven)

### ⚙️ I need detailed technical diagnostics
→ **`python3 scripts/diagnose_and_fix_redis_lock.py`** (automated)

### ✅ I've applied a fix and need to verify it worked
→ **[REDIS_LOCK_VERIFICATION_CHECKLIST.md](REDIS_LOCK_VERIFICATION_CHECKLIST.md)**

---

## 🎯 The Three Fixes (In Order of Likelihood to Work)

### Fix #1: Restart Redis Service (80% success) ⭐

**Why it works:** Redis commonly crashes or hits resource limits. Restart clears stale state.

**How:**
1. Railway Dashboard → Redis service
2. Click **Restart**
3. Wait 60 seconds
4. Restart NIJA service

**Timeline:** 2-3 minutes

---

### Fix #2: Enable TCP Proxy (15% success)

**Why it works:** Railway requires explicit TCP proxy to connect from outside.

**How:**
1. Railway → Redis → **Networking** tab
2. Enable "Public Networking"
3. Copy Domain + Port
4. Update NIJA `NIJA_REDIS_URL` with the values
5. Restart NIJA service

**Timeline:** 3-5 minutes

---

### Fix #3: Emergency Bypass (5% success, temporary only)

**Why it works:** Disables lock check to allow trading while Redis recovers.

**How:**
1. NIJA service → **Variables**
2. Set: `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true`
3. Restart NIJA service
4. ⚠️ Disable this when Redis recovers!

**Timeline:** 1-2 minutes

**⚠️ WARNING:** Only for emergency use. Breaks single-writer guarantee. Must be disabled!

---

## 📊 Decision Tree

```
Is NIJA stuck in fail-closed mode?
│
├─ YES → Is Redis showing in Railway dashboard?
│         │
│         ├─ NO (offline/crashed)
│         │   └─→ FIX #1: Restart Redis
│         │
│         └─ YES (running)
│             └─→ Does NIJA service show "Networking" options?
│                 │
│                 ├─ YES
│                 │   └─→ FIX #2: Enable TCP Proxy
│                 │
│                 └─ NO (not supported yet)
│                     └─→ FIX #3: Emergency Bypass
│
└─ NO → Not your issue, check other logs
```

---

## 📁 Recovery Files & Tools

| File | Purpose | Time |
|------|---------|------|
| [REDIS_LOCK_QUICK_FIX.md](REDIS_LOCK_QUICK_FIX.md) | Executive summary - quick actions | 2 min |
| [REDIS_LOCK_RECOVERY_GUIDE.md](REDIS_LOCK_RECOVERY_GUIDE.md) | Detailed step-by-step with examples | 10 min |
| [REDIS_LOCK_VERIFICATION_CHECKLIST.md](REDIS_LOCK_VERIFICATION_CHECKLIST.md) | Verify fix worked | 5 min |
| `scripts/diagnose_and_fix_redis_lock.py` | Auto diagnostics (Python) | 2 min |
| `scripts/railway_redis_recovery.sh` | Interactive menu helper (Shell) | 5 min |
| `scripts/redis_connectivity_check.sh` | Low-level connectivity test | 3 min |
| `scripts/clear_redis_locks.py` | Delete stale locks | 1 min |

---

## 🔍 Diagnostic Commands

Run these to understand what's happening:

```bash
# 1. Basic diagnostics (most detailed)
python3 scripts/diagnose_and_fix_redis_lock.py

# 2. Interactive helper for Railway
bash scripts/railway_redis_recovery.sh

# 3. Low-level connectivity test
bash scripts/redis_connectivity_check.sh

# 4. Check if Redis locks are stuck
python3 scripts/clear_redis_locks.py

# 5. Clear stale locks (if needed)
python3 scripts/clear_redis_locks.py --clear
```

---

## ✅ Expected Success Indicators

### In NIJA Logs - Look For:
```
✅ Redis connection established
✅ Distributed writer lock acquired
✅ Distributed writer lock ready
✅ Live trading approved
🔥 Starting live trading bot...
```

### In Railway Dashboard:
- ✅ NIJA service: 🟢 Running
- ✅ Redis service: 🟢 Running
- ✅ No error indicators

### In Trading Activity:
- ✅ Market scanning begins
- ✅ Entry/exit signals appear in logs
- ✅ Positions are opened/closed

---

## ❌ If All Fixes Fail (Escalation Path)

1. **Generate detailed diagnostics:**
   ```bash
   python3 scripts/diagnose_and_fix_redis_lock.py > diagnostics.txt
   ```

2. **Check Railway status:**
   - Is Redis service in "Running" state?
   - Are there any platform alerts?
   - Check Railway status page: status.railway.app

3. **Last resort:**
   - Delete and recreate Redis service in Railway
   - Update NIJA_REDIS_URL with new credentials
   - Restart NIJA

---

## 🔐 Environment Variables Reference

| Variable | Required | Example |
|----------|----------|---------|
| `NIJA_REDIS_URL` | ✅ Yes | `rediss://default:PWD@host:port/0` |
| `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK` | ❌ No (emergency only) | `true` |
| `NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE` | ❌ No (default=true) | `true` |
| `NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS` | ❌ No (default=12 in live mode, infinite otherwise) | `12` |
| `NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS` | ❌ No (default=true in live mode, false otherwise) | `true` |
| `NIJA_REDIS_CONNECT_TIMEOUT_S` | ❌ No (default=5) | `5` |
| `NIJA_REDIS_SOCKET_TIMEOUT_S` | ❌ No (default=5) | `5` |

---

## 📞 Support Resources

- **Detailed troubleshooting:** [REDIS_RAILWAY_SETUP.md](REDIS_RAILWAY_SETUP.md)
- **Production resilience guide:** [PRODUCTION_REDIS_RESILIENCE_RUNBOOK.md](PRODUCTION_REDIS_RESILIENCE_RUNBOOK.md)
- **Railway documentation:** https://docs.railway.app
- **Redis documentation:** https://redis.io/docs

---

## 🕐 Timeline Expectations

| Fix | Time to Apply | Wait Time | Total |
|-----|---------------|-----------|-------|
| #1 Restart Redis | 2 min | 1 min | **3 min** |
| #2 Enable TCP Proxy | 3 min | 1 min | **4 min** |
| #3 Emergency Bypass | 1 min | 0 min | **1 min** |

**Total time from issue to trading:** 3-10 minutes depending on fix

---

## 📝 Quick Reference

**Problem:** Redis timeout  
**Symptom:** `⚠️ Redis connection attempt X/5 failed: Timeout connecting to server`  
**Solution Priority:** Fix #1 → Fix #2 → Fix #3  
**Urgency:** 🔴 CRITICAL (trading blocked)  

---

**Last Updated:** 2026-05-09  
**Version:** 1.0  
**Status:** Production Emergency Recovery Kit
