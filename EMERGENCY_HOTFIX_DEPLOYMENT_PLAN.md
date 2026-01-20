# C) FULL EMERGENCY HOTFIX DEPLOYMENT PLAN

**Date:** January 20, 2026  
**Priority:** CRITICAL  
**Estimated Time:** 15-30 minutes  
**Risk Level:** MEDIUM (requires production deployment)

---

## Pre-Deployment Checklist

### Environment Verification

- [ ] Railway/Render/Docker environment identified
- [ ] Current deployment method documented (Git push, CLI, Docker)
- [ ] Backup of current running version saved
- [ ] Current open positions documented
- [ ] Current account balances recorded
- [ ] Emergency rollback plan prepared

### Required Access

- [ ] Git repository write access
- [ ] Railway/Render dashboard access
- [ ] Broker API access (Coinbase, Kraken)
- [ ] Database/logs access for monitoring
- [ ] Emergency contact information ready

### Pre-Flight Checks

```bash
# 1. Check current bot status
python3 display_broker_status.py > pre_deploy_status.txt

# 2. Export current positions
python3 export_positions.py > pre_deploy_positions.json

# 3. Check for active trading
tail -f logs/trading.log

# 4. Verify no emergency mode is active
ls -la LIQUIDATE_ALL_NOW.conf TRADING_EMERGENCY_STOP.conf
```

---

## Deployment Steps

### Phase 1: Preparation (5 minutes)

#### Step 1.1: Stop New Trades

```bash
# Enable sell-only mode to prevent new entries
export HARD_BUY_OFF=1

# OR create emergency stop file
touch TRADING_EMERGENCY_STOP.conf

# Verify in logs
tail -f logs/trading.log | grep "BUY BLOCKED"
```

**Expected Output:**
```
🛑 BUY BLOCKED at broker layer: SELL-ONLY mode or HARD_BUY_OFF active
   Symbol: BTC-USD
   Reason: HARD_BUY_OFF
```

#### Step 1.2: Document Current State

```bash
# Save current balances
python3 display_broker_status.py > backup/balances_$(date +%Y%m%d_%H%M%S).txt

# Save current positions
python3 check_coinbase_positions.py > backup/positions_$(date +%Y%m%d_%H%M%S).txt

# Save git commit hash
git log -1 --oneline > backup/current_commit.txt

# Save environment variables (excluding secrets)
env | grep -E "(HARD_BUY|DATA_DIR|PORT)" > backup/current_env.txt
```

#### Step 1.3: Pull Latest Code

```bash
# Ensure clean working directory
git status

# Stash any local changes
git stash

# Pull latest fixes
git pull origin main

# Verify files exist
ls -la SELL_OVERRIDE_PATCH_DROPIN.py
ls -la KRAKEN_RAILWAY_NONCE_SETUP.md
ls -la bot/global_kraken_nonce.py
```

### Phase 2: Apply Fixes (10 minutes)

#### Step 2.1: Verify Critical Files

```bash
# Check sell override is in place
grep -n "emergency_file" bot/broker_manager.py | head -5

# Check global nonce manager exists
python3 -c "from bot.global_kraken_nonce import get_global_kraken_nonce; print('✅ Import successful')"

# Check forced exit function exists
grep -n "def force_exit_position" bot/execution_engine.py
```

**Expected:**
```
bot/broker_manager.py:2267:    emergency_file = os.path.join(...)
bot/execution_engine.py:545:    def force_exit_position(self, broker_client, symbol: str, ...
✅ Import successful
```

#### Step 2.2: Install Dependencies

```bash
# Update Python packages
pip install -r requirements.txt

# Verify critical packages
pip show coinbase-advanced-py krakenex
```

#### Step 2.3: Run Test Suite

```bash
# Test critical safeguards
python3 test_critical_safeguards_jan_19_2026.py

# Test Kraken fixes
python3 test_kraken_fixes_jan_19_2026.py

# Test nonce persistence
python3 test_nonce_persistence.py
```

**Expected:** All tests pass with ✅

If any tests fail, **STOP** and investigate before proceeding.

### Phase 3: Railway/Render Configuration (5 minutes)

#### Step 3.1: Configure Environment Variables

**Railway Dashboard:**
1. Go to project → Service → Variables
2. Add/update:
   ```bash
   DATA_DIR=/app/data
   HARD_BUY_OFF=1  # Keep sell-only during deployment
   ```
3. Save changes

**Render Dashboard:**
1. Go to service → Environment
2. Add/update same variables
3. Save changes

#### Step 3.2: Configure Persistent Volume (Railway Only)

1. Go to Service → Settings → Volumes
2. Verify volume exists:
   - **Name:** `nija-data`
   - **Mount Path:** `/app/data`
3. If missing, create volume (see KRAKEN_RAILWAY_NONCE_SETUP.md)

#### Step 3.3: Update Dockerfile (if needed)

```dockerfile
# Ensure data directory exists
RUN mkdir -p /app/data && chmod 777 /app/data

# Ensure volume mount point is ready
VOLUME ["/app/data"]
```

### Phase 4: Deploy to Production (5-10 minutes)

#### Step 4.1: Commit and Push

```bash
# Add any local changes
git add .

# Commit with clear message
git commit -m "Deploy emergency hotfixes: sell override, global nonce, safeguards"

# Push to main branch
git push origin main
```

#### Step 4.2: Monitor Deployment

**Railway:**
1. Watch build logs in dashboard
2. Wait for "Build successful"
3. Wait for "Deploy successful"
4. Check runtime logs

**Render:**
1. Watch deploy progress
2. Wait for "Live" status
3. Check runtime logs

**Docker (self-hosted):**
```bash
# Pull latest image
docker pull <your-image>

# Stop current container
docker stop nija-bot

# Remove old container
docker rm nija-bot

# Start new container with volume
docker run -d \
  --name nija-bot \
  -v nija-data:/app/data \
  --env-file .env \
  <your-image>

# Check logs
docker logs -f nija-bot
```

#### Step 4.3: Verify Startup

Watch logs for these critical patterns:

```bash
# Railway/Render
railway logs  # or render logs

# Docker
docker logs -f nija-bot
```

**Look for:**
```
✅ Global Kraken Nonce Manager initialized (persisted nonce: XXXXX, API serialization: ENABLED)
✅ Using GLOBAL Kraken Nonce Manager for MASTER (nanosecond precision)
💰 Total Available: $XXXX.XX
🔍 Broker connection successful
```

**Do NOT proceed if you see:**
```
❌ Kraken API error: EAPI:Invalid nonce
❌ Could not connect to broker
❌ Failed to initialize
```

### Phase 5: Post-Deployment Verification (10 minutes)

#### Step 5.1: Verify Nonce Persistence

```bash
# Check if nonce file exists (Railway/Render may need SSH access)
# Or check via health endpoint if implemented

# Watch logs for nonce loading
grep "Loaded persisted nonce" <logs>
```

**Expected:**
```
Loaded persisted nonce: 1737159471234567890, using: 1737159471234567891
```

#### Step 5.2: Test Sell Override

**Option A: Manual Test (SAFE)**

```bash
# Create test trigger file
touch LIQUIDATE_ALL_NOW.conf

# Watch logs for emergency mode activation
tail -f logs/trading.log | grep "EMERGENCY MODE"

# Remove trigger file
rm LIQUIDATE_ALL_NOW.conf
```

**Expected in logs:**
```
   EMERGENCY MODE: Skipping pre-flight balance checks
```

**Option B: Live Test (CAUTION)**

Only if you have a small position to exit:

```bash
# Activate emergency mode
touch LIQUIDATE_ALL_NOW.conf

# Let bot detect and exit a position
# Watch logs carefully

# Deactivate emergency mode
rm LIQUIDATE_ALL_NOW.conf
```

#### Step 5.3: Test Kraken API

Watch for successful Kraken balance checks:

```bash
tail -f logs/trading.log | grep "Kraken Balance"
```

**Expected:**
```
💰 Kraken Balance (MASTER):
   ✅ Available USD:  $XXXX.XX
   ✅ Available USDT: $XXXX.XX
```

**Should NOT see:**
```
❌ Kraken API error: EAPI:Invalid nonce
```

#### Step 5.4: Resume Normal Trading

```bash
# Remove sell-only mode
unset HARD_BUY_OFF

# OR in Railway/Render dashboard, set:
HARD_BUY_OFF=0

# Verify trading resumes
tail -f logs/trading.log | grep "BUY\|SELL"
```

#### Step 5.5: Monitor for 30 Minutes

Watch logs for:

**✅ Good Patterns:**
```
✅ Using GLOBAL Kraken Nonce Manager
💰 Pre-flight balance check for BTC-USD
📤 Placing BUY order: BTC-USD, quote_size=$50.00
📤 Placing SELL order: BTC-USD, base_size=0.00123456
✅ Order successful: <order_id>
```

**⚠️ Warning Patterns:**
```
⚠️ Using last known balance: $XXXX.XX
⚠️ Balance mismatch: tracked X.XX but only X.XX available
🧟 ZOMBIE POSITION DETECTED: SYMBOL
```

**🛑 Critical Patterns:**
```
🛑 EMERGENCY STOP LOSS HIT: SYMBOL at -X.XX%
🛑 FORCED EXIT FAILED AFTER 2 ATTEMPTS
❌ Kraken marked unavailable after 3 consecutive errors
❌ Kraken API error: EAPI:Invalid nonce
```

---

## Rollback Procedures

### If Critical Issues Occur

#### Immediate Actions

```bash
# 1. STOP ALL TRADING
touch TRADING_EMERGENCY_STOP.conf
export HARD_BUY_OFF=1

# 2. Check current positions
python3 check_coinbase_positions.py
python3 display_broker_status.py

# 3. If positions need emergency exit
touch LIQUIDATE_ALL_NOW.conf
# (This activates sell override even in old code if present)
```

#### Rollback Code

```bash
# Get previous commit hash
git log --oneline -5

# Rollback to previous version
git revert HEAD
git push origin main

# OR force reset (use with caution)
git reset --hard <previous_commit_hash>
git push -f origin main
```

#### Railway/Render Rollback

**Railway:**
1. Go to Deployments
2. Find previous successful deployment
3. Click "..." → "Redeploy"
4. Confirm

**Render:**
1. Go to service
2. Click "Manual Deploy"
3. Select previous commit
4. Deploy

**Docker:**
```bash
# Use previous image tag
docker pull <your-image>:<previous-tag>

# Stop current
docker stop nija-bot && docker rm nija-bot

# Start previous version
docker run -d --name nija-bot <your-image>:<previous-tag>
```

#### Verify Rollback

```bash
# Check commit
git log -1 --oneline

# Check bot is running
ps aux | grep python | grep bot

# Check logs are clean
tail -f logs/trading.log
```

---

## Monitoring Checklist

### First 30 Minutes

- [ ] No "Invalid nonce" errors (Kraken)
- [ ] Balance checks working (all brokers)
- [ ] Orders executing successfully
- [ ] No emergency stop-loss triggers
- [ ] Nonce file persisting (check after restart)
- [ ] No zombie positions detected

### First 24 Hours

- [ ] P&L trending positive or neutral
- [ ] No forced exits failed
- [ ] API error rate < 1%
- [ ] All brokers showing available
- [ ] Position tracking accurate

### First Week

- [ ] No nonce collisions (Kraken)
- [ ] Emergency modes never triggered
- [ ] Sell override working when activated
- [ ] All safeguards functional
- [ ] No rollbacks required

---

## Emergency Contacts

### Critical Issues

**Immediate Response:**
1. Stop trading: `touch TRADING_EMERGENCY_STOP.conf`
2. Check positions: `python3 display_broker_status.py`
3. Review logs: `tail -100 logs/trading.log`
4. Document issue: Create GitHub issue with logs

**If Rollback Needed:**
1. Follow "Rollback Code" section above
2. Verify old version running
3. Monitor for stability
4. Document root cause

### Support Resources

- GitHub Issues: https://github.com/dantelrharrell-debug/Nija/issues
- Documentation: See README.md, TROUBLESHOOTING.md
- Logs: `/var/log/nija/` or Railway/Render logs dashboard

---

## Success Criteria

### Deployment Successful If:

✅ **All tests pass**
- test_critical_safeguards_jan_19_2026.py: PASS
- test_kraken_fixes_jan_19_2026.py: PASS
- test_nonce_persistence.py: PASS

✅ **Core functionality working**
- Global nonce manager initialized
- Nonce persistence verified after restart
- Balance checks successful (all brokers)
- Orders executing without errors

✅ **Emergency features operational**
- Sell override activates with LIQUIDATE_ALL_NOW.conf
- Emergency stop-loss at -1.25% functional
- Forced exit bypasses all filters

✅ **No critical errors**
- No "Invalid nonce" errors
- No balance fetch failures
- No order placement failures
- No forced exit failures

✅ **Monitoring shows health**
- API error rate < 1%
- All brokers available
- P&L tracking accurately
- No zombie positions

---

## Timeline Summary

| Phase | Duration | Critical Path |
|-------|----------|---------------|
| Preparation | 5 min | Stop new trades, backup state |
| Apply Fixes | 10 min | Verify code, run tests |
| Configuration | 5 min | Update env vars, volumes |
| Deployment | 5-10 min | Push code, monitor deploy |
| Verification | 10 min | Test features, resume trading |
| Monitoring | 30 min | Watch for issues, verify stability |
| **TOTAL** | **35-40 min** | **Plus 30 min monitoring** |

---

## Post-Deployment Report

**Complete after successful deployment:**

```markdown
# Emergency Hotfix Deployment - Post-Deployment Report

**Date:** <date>
**Time:** <time>
**Deployed By:** <name>
**Deployment Method:** Railway/Render/Docker
**Commit Hash:** <hash>

## Pre-Deployment Status
- Open Positions: <count>
- Total Balance: $<amount>
- Bot Version: <previous_commit>

## Deployment Summary
- Start Time: <time>
- End Time: <time>
- Duration: <minutes>
- Issues Encountered: <list or "None">

## Post-Deployment Status
- Open Positions: <count>
- Total Balance: $<amount>
- Bot Version: <current_commit>

## Verification Results
- [ ] Nonce persistence working
- [ ] Sell override functional
- [ ] Kraken API working
- [ ] Coinbase API working
- [ ] All tests passing
- [ ] No critical errors

## Monitoring (First 30 Min)
- API Errors: <count>
- Orders Placed: <count>
- Emergency Triggers: <count>
- Rollbacks: <count>

## Notes
<any additional observations>

## Status
✅ SUCCESSFUL / ⚠️ ISSUES NOTED / ❌ ROLLED BACK
```

---

**Status:** ✅ READY FOR DEPLOYMENT  
**Last Updated:** January 20, 2026  
**Next Review:** After successful deployment
