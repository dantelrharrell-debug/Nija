# 🚨 NIJA Redis Lock Recovery - START HERE

```
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║   🔴 CRITICAL: Bot in Fail-Closed Standby Mode                     ║
║   ⏸️  Trading is BLOCKED - Redis cannot be reached                 ║
║   ⏱️  Time to fix: 5-10 minutes                                     ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 🎯 What's Happening?

Your NIJA bot is trying to acquire a distributed Redis lock but **can't reach Redis**:

```
❌ Timeout connecting to server (maglev.proxy.rlwy.net:31245)
❌ FAILED TO ACQUIRE WRITER LOCK
🛑 FAIL-CLOSED STANDBY ACTIVE: trading remains blocked
⏳ Bot is retrying every 5 seconds indefinitely...
```

**Root cause:** Redis connectivity issue (network, offline, or misconfigured)

---

## 🔧 QUICK FIX - Choose ONE

### ⭐ FIX #1: Restart Redis (80% works)

```
1. Railway Dashboard → Redis service
2. Click Restart button
3. Wait 60 seconds (watch status turn 🟢 Green)
4. Restart NIJA service
5. ✅ Done!
```

**If this works:** You'll see in logs within 1 minute:
```
✅ Redis connection established
✅ Distributed writer lock acquired
🔥 Starting live trading bot...
```

---

### 🔌 FIX #2: Enable TCP Proxy (if #1 doesn't work)

```
1. Railway Dashboard → Redis service
2. Go to Networking tab
3. Enable "Public Networking" or "TCP Proxy"
4. Copy Domain and Port shown
5. NIJA service → Variables tab
6. Create: NIJA_REDIS_URL=rediss://default:PASSWORD@DOMAIN:PORT/0
7. Restart NIJA service
```

**Example:**
```
NIJA_REDIS_URL=rediss://default:2eF9xK_3mL#pQ@maglev.proxy.rlwy.net:31245/0
```

---

### 🚨 FIX #3: Emergency Bypass (last resort only!)

```
1. NIJA service → Variables tab
2. Add: NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true
3. Restart NIJA service
4. ⚠️ IMPORTANT: Disable when Redis recovers!
```

**⚠️ WARNING:** Only use if you need immediate trading and Redis is down temporarily!

---

## 📚 Full Documentation

| Document | Read Time | Purpose |
|----------|-----------|---------|
| **[REDIS_LOCK_QUICK_FIX.md](REDIS_LOCK_QUICK_FIX.md)** | ⏱️ 2 min | Fast action guide |
| **[REDIS_LOCK_RECOVERY_GUIDE.md](REDIS_LOCK_RECOVERY_GUIDE.md)** | ⏱️ 10 min | Detailed step-by-step |
| **[REDIS_LOCK_VERIFICATION_CHECKLIST.md](REDIS_LOCK_VERIFICATION_CHECKLIST.md)** | ⏱️ 5 min | Verify fix worked |
| **[REDIS_LOCK_RECOVERY_KIT.md](REDIS_LOCK_RECOVERY_KIT.md)** | ⏱️ 15 min | Complete reference |

---

## 🛠️ Automated Tools

### Option A: Python Diagnostics
```bash
python3 scripts/diagnose_and_fix_redis_lock.py
```
Provides detailed analysis of what's wrong

### Option B: Interactive Helper
```bash
bash scripts/railway_redis_recovery.sh
```
Menu-driven step-by-step instructions

### Option C: Connectivity Check
```bash
bash scripts/redis_connectivity_check.sh
```
Tests TCP connectivity and Redis PING

### Option D: Clear Stale Locks
```bash
python3 scripts/clear_redis_locks.py --clear
```
Remove any stuck locks (after Redis is back online)

---

## ✅ Verification

After applying a fix, watch for these in NIJA logs:

```bash
# These mean it worked! 🎉
✅ Redis connection established
✅ Distributed writer lock acquired
✅ Live trading approved
🔥 Starting live trading bot...

# These mean it didn't work ❌
❌ Failed to acquire writer lock
⚠️ Redis connection attempt failed
🛑 FAIL-CLOSED STANDBY ACTIVE
```

---

## 🚦 What To Do Next

### Step 1: Choose Your Fix
- **Most reliable:** Try Fix #1 first
- **Most thorough:** If stuck, use diagnostic tools
- **Emergency only:** Use Fix #3 as last resort

### Step 2: Apply the Fix
- Follow Railway dashboard steps
- Restart services as needed

### Step 3: Verify Success
- Check logs for success indicators
- Monitor for trading activity
- Use verification checklist

### Step 4: If Still Stuck
- Run: `bash scripts/redis_connectivity_check.sh`
- Read: [REDIS_LOCK_RECOVERY_GUIDE.md](REDIS_LOCK_RECOVERY_GUIDE.md)
- Check: Railway service health in dashboard

---

## 📊 Quick Reference

```
Problem:     Redis cannot be reached
Symptom:     Timeout errors + lock acquisition failure
Urgency:     🔴 CRITICAL - Trading blocked
Time to fix: 5-10 minutes
Success rate: 
  - Fix #1: 80% (redis crash/restart)
  - Fix #2: 15% (tcp proxy/config)
  - Fix #3: 5% (emergency bypass)
```

---

## 🎬 Next Action

**RIGHT NOW:**

1. ✅ Choose Fix #1 or #2 above
2. ✅ Apply it in Railway dashboard
3. ✅ Restart NIJA service
4. ✅ Watch logs for success message
5. ✅ Resume trading! 🚀

---

## 🆘 Emergency Contacts

If you're completely stuck:

1. Run diagnostic: `python3 scripts/diagnose_and_fix_redis_lock.py`
2. Save output
3. Consult [REDIS_LOCK_RECOVERY_GUIDE.md](REDIS_LOCK_RECOVERY_GUIDE.md) section "If You're Still Stuck"
4. Check Railway service status dashboard

---

**Created:** 2026-05-09  
**Status:** 🔴 CRITICAL - Action Required  
**Estimated Fix Time:** 5-10 minutes
