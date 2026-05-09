# NIJA Redis Lock Recovery Verification Checklist

**Goal:** Verify that you've correctly resolved the Redis connectivity issue

**Start Time:** _________  
**Fix Applied:** _________  
**Completion Time:** _________

---

## Phase 1: Diagnosis ✓

- [ ] I identified why Redis is unreachable (choose one):
  - [ ] Redis service is offline/crashed
  - [ ] TCP Proxy is not enabled
  - [ ] NIJA_REDIS_URL is incorrect
  - [ ] Network connectivity issue

- [ ] I verified the issue matches the symptoms:
  - [ ] Logs show "Timeout connecting to server"
  - [ ] Logs show "FAILED TO ACQUIRE WRITER LOCK"
  - [ ] Bot is in "FAIL-CLOSED STANDBY ACTIVE" mode

---

## Phase 2: Applied Recovery Fix ✓

### If using Option A (Restart Redis):
- [ ] Navigated to Railway Dashboard
- [ ] Found and clicked Redis service
- [ ] Clicked Restart button
- [ ] Waited 60 seconds for restart
- [ ] Verified Redis status is 🟢 Green
- [ ] Restarted NIJA service

### If using Option B (Enable TCP Proxy):
- [ ] Navigated to Railway → Redis → Networking tab
- [ ] Enabled Public Networking or TCP Proxy
- [ ] Copied Domain name (e.g., `maglev.proxy.rlwy.net`)
- [ ] Copied Port number (e.g., `31245`)
- [ ] Went to NIJA service → Variables
- [ ] Created/updated `NIJA_REDIS_URL` with format:
  ```
  rediss://default:PASSWORD@DOMAIN:PORT/0
  ```
- [ ] Used correct Redis password (from Redis service → Variables)
- [ ] Verified URL uses `rediss://` (not `redis://`)
- [ ] Restarted NIJA service

### If using Option C (Emergency Bypass):
- [ ] Went to NIJA service → Variables
- [ ] Set: `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true`
- [ ] Verified this is a **temporary fix only**
- [ ] Restarted NIJA service
- [ ] **Scheduled reminder to disable this when Redis recovers**

---

## Phase 3: Verification ✓

### Check 1: Service Status
- [ ] NIJA service shows 🟢 Running in Railway dashboard
- [ ] Redis service shows 🟢 Running in Railway dashboard
- [ ] No error indicators on either service

### Check 2: Logs - Look for Success Messages
Go to NIJA service → Logs and verify these messages appear:

- [ ] `✅ Redis connection established` (or similar)
- [ ] `🧯 Fail-closed config | ...` appears at startup
- [ ] In live mode, `max_retry_attempts=12` unless intentionally overridden
- [ ] `✅ Distributed writer lock acquired` (or similar)
- [ ] `✅ Distributed writer lock ready`
- [ ] `✅ Live trading approved: LIVE_CAPITAL_VERIFIED=true`
- [ ] `🔥 Starting live trading bot...` or similar

### Check 3: Logs - Check for Errors
Verify these error patterns do NOT appear:

- [ ] NO `⚠️ Redis connection attempt ... failed`
- [ ] NO `❌ FAILED TO ACQUIRE WRITER LOCK`
- [ ] NO `🛑 FAIL-CLOSED STANDBY ACTIVE`
- [ ] NO `Timeout connecting to server`
- [ ] If Redis is unreachable in live mode, process exits after retry cap (no infinite standby loop)

### Check 4: Trading Activity
- [ ] Bot has started market scanning
- [ ] Logs show entry/exit signals (or paper trading activity)
- [ ] No continuous retry loops in logs

---

## Phase 4: Post-Recovery ✓

### If using Emergency Bypass:
- [ ] Set calendar reminder: "Disable NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"
- [ ] Will manually disable once Redis is fully stable
- [ ] Understand this should ONLY be 1-3 hours max

### Regular Maintenance:
- [ ] Verified NIJA is running with exactly 1 replica (check `railway.json`)
- [ ] Backed up current working environment variables
- [ ] Documented what caused the issue for future reference

---

## Troubleshooting If Still Stuck ⚠️

If you see continued failures, run diagnostics:

```bash
# Path 1: Python diagnostic
python3 scripts/diagnose_and_fix_redis_lock.py

# Path 2: Shell-based connectivity check
bash scripts/redis_connectivity_check.sh

# Path 3: Interactive helper
bash scripts/railway_redis_recovery.sh
```

### Common Issues and Fixes:

| Issue | Symptoms | Fix |
|-------|----------|-----|
| Redis crashed | 🔴 Red status, then 🟢 Green after restart | Restart Redis service |
| TCP Proxy disabled | "Timeout" errors persist | Enable TCP Proxy in Networking |
| Wrong password | "AUTH failed" in logs | Verify REDIS_PASSWORD matches URL |
| Wrong port | "Connection refused" errors | Use port from Networking tab, not 6379 |
| Wrong URL scheme | Still timing out | Change `redis://` → `rediss://` |
| Multiple NIJA replicas | Lock never acquired | Set `numReplicas=1` in railway.json |

---

## 📋 Success Confirmation

- [ ] NIJA service is 🟢 Running
- [ ] Redis service is 🟢 Running
- [ ] No error logs for 2+ minutes
- [ ] At least one trading signal appeared
- [ ] Bot is actively scanning markets or executing trades

---

## 🎉 Recovery Complete!

Once all checkboxes are complete, your NIJA bot should be back online and trading normally.

**If any issues remain:**
1. Repeat Phase 3 (Verification)
2. Run diagnostics scripts
3. Check documentation links in REDIS_LOCK_RECOVERY_GUIDE.md

---

**Recovery Started:** _________  
**Recovery Completed:** _________  
**Total Time:** _________  
**Result:** ✅ SUCCESS / ⚠️ PARTIAL / ❌ FAILED

