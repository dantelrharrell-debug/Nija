# RECURRING DISCONNECTION ISSUE - SOLUTION GUIDE
## January 16, 2026

---

## Problem Statement

**Issue**: "Master and all users are disconnected **again** - why does this keep happening?"

**Observed Symptoms**:
```
✅ MASTER ACCOUNT: TRADING (Broker: COINBASE)
⚪ USER: Daivon Frazier: NOT CONFIGURED (Broker: KRAKEN, Credentials not set)
⚪ USER: Tania Gilbert: NOT CONFIGURED (Broker: KRAKEN, Credentials not set)
⚪ USER: Tania Gilbert: NOT CONFIGURED (Broker: ALPACA, Credentials not set)
```

**Key Insight**: The word "again" indicates this is a **RECURRING** issue, not a one-time setup problem.

---

## Root Cause Analysis

### Why Credentials Keep Getting Lost

There are several common causes for recurring credential loss:

#### 1. **Environment Variables Not Persisted in Deployment Platform** (MOST COMMON)

**Problem**:
- Credentials are set in shell session or local .env file
- NOT set in Railway/Render dashboard
- Each deployment/restart loses the credentials

**Evidence**:
- Credentials work after manual setup
- Stop working after deployment restart
- Need to be re-entered repeatedly

**Solution**:
- Set credentials in Railway/Render dashboard
- NOT in local .env (which doesn't deploy)
- NOT in shell session (which doesn't persist)

#### 2. **Deployment Platform Resets Environment Variables**

**Problem**:
- Some deployment platforms reset environment variables on:
  - Service recreation
  - Plan changes
  - Platform maintenance
  - Project transfers

**Solution**:
- Export environment variables as backup
- Re-verify after any platform changes
- Use platform's environment variable validation

#### 3. **Credentials Overwritten by Config Files**

**Problem**:
- `.env.example` committed to git with empty values
- Deployment pulls from git and overwrites
- Environment variables get cleared

**Solution**:
- **NEVER** commit `.env` to git
- Ensure `.env` is in `.gitignore`
- Use deployment platform's UI for credentials

#### 4. **Multiple Deployment Instances**

**Problem**:
- Multiple deployments (dev, staging, prod)
- Credentials set in one, not in others
- Confusion about which instance is running

**Solution**:
- Document which deployment is active
- Set credentials in ALL deployments
- Use clear naming for environments

#### 5. **API Key Rotation/Expiration**

**Problem**:
- API keys regenerated on broker platform
- Old keys in environment variables
- Keys expire or get revoked

**Solution**:
- Update environment variables when rotating keys
- Document key rotation dates
- Set calendar reminders for key updates

---

## Comprehensive Solution

### Step 1: Verify Current Environment

Run the new verification tool:

```bash
python3 verify_credentials_persistence.py
```

This will show:
- ✅ Which credentials are set
- ❌ Which credentials are missing
- 🔄 Where credentials are stored (local vs deployment)
- 📋 Exact commands to fix missing credentials

### Step 2: Set Credentials in Deployment Platform

**For Railway** (RECOMMENDED for persistence):

1. Go to https://railway.app/
2. Select your NIJA service
3. Click **"Variables"** tab
4. Click **"New Variable"**
5. Add each credential:

   **Master Accounts**:
   ```
   COINBASE_API_KEY=<your-coinbase-key>
   COINBASE_API_SECRET=<your-coinbase-secret>
   
   KRAKEN_MASTER_API_KEY=<your-master-kraken-key>
   KRAKEN_MASTER_API_SECRET=<your-master-kraken-secret>
   
   ALPACA_API_KEY=<your-alpaca-key>
   ALPACA_API_SECRET=<your-alpaca-secret>
   ```

   **User: Daivon Frazier (Kraken)**:
   ```
   KRAKEN_USER_DAIVON_API_KEY=<daivon-kraken-key>
   KRAKEN_USER_DAIVON_API_SECRET=<daivon-kraken-secret>
   ```

   **User: Tania Gilbert (Kraken)**:
   ```
   KRAKEN_USER_TANIA_API_KEY=<tania-kraken-key>
   KRAKEN_USER_TANIA_API_SECRET=<tania-kraken-secret>
   ```

   **User: Tania Gilbert (Alpaca)**:
   ```
   ALPACA_USER_TANIA_API_KEY=<tania-alpaca-key>
   ALPACA_USER_TANIA_API_SECRET=<tania-alpaca-secret>
   ALPACA_USER_TANIA_PAPER=true
   ```

6. Click **"Save"** - Railway will auto-redeploy
7. Wait 2-3 minutes for deployment to complete

**For Render**:

1. Go to https://render.com/
2. Select your NIJA service
3. Click **"Environment"** tab
4. Click **"Add Environment Variable"**
5. Add all credentials (same as above)
6. Click **"Save Changes"**
7. Click **"Manual Deploy"** → **"Deploy latest commit"**
8. Wait 3-5 minutes for deployment

### Step 3: Verify Persistence

**Immediately after setting credentials**:

```bash
python3 verify_credentials_persistence.py
```

**Expected output**:
```
✅ Master Accounts Configured: 3/3
   ✅ Coinbase Master
   ✅ Kraken Master
   ✅ Alpaca Master

✅ User Accounts Configured: 3/3
   ✅ Daivon Frazier (KRAKEN)
   ✅ Tania Gilbert (KRAKEN)
   ✅ Tania Gilbert (ALPACA)

🚀 Deployment Platform: Railway
✅ SUCCESS: All configured accounts have valid credentials
```

### Step 4: Test After Restart

**Restart the deployment**:

Railway:
```
Dashboard → Select Service → Settings → Restart
```

Render:
```
Dashboard → Select Service → Manual Deploy → Deploy latest commit
```

**After restart, verify again**:

```bash
python3 verify_credentials_persistence.py
```

**If credentials are STILL SET** → ✅ Problem solved!  
**If credentials are MISSING** → ⚠️  See "Advanced Troubleshooting" below

---

## New Features to Prevent Recurring Issues

### 1. Credential Health Monitoring

The bot now monitors credentials in real-time:

```python
# Automatically started in bot/trading_strategy.py
from credential_health_monitor import start_credential_monitoring
credential_monitor = start_credential_monitoring()
```

**What it does**:
- Checks credentials every 5 minutes
- Detects when credentials disappear
- Logs timestamp when credentials were lost
- Alerts you immediately with clear error messages

**Log output when credentials are lost**:
```
⚠️  CREDENTIAL LOST: KRAKEN_USER_TANIA_API_KEY was valid, now missing
   Last seen valid: 2026-01-16T20:45:00
   Time elapsed: 300.0 seconds
```

### 2. Credential Persistence Verification Tool

Run anytime to check credential status:

```bash
python3 verify_credentials_persistence.py
```

**Features**:
- Shows which credentials are set/missing
- Detects deployment platform (Railway/Render/Local)
- Generates exact fix commands
- Validates credential format (not just empty/whitespace)
- Shows credential preview (first 8 chars) for verification

### 3. Startup Credential Validation

The bot now validates credentials on startup and warns if missing:

```
🔍 Starting credential health monitoring...
   ✅ Credential monitoring active (checks every 5 minutes)

⚠️  User account credentials not configured:
   - Daivon Frazier (KRAKEN): KRAKEN_USER_DAIVON_API_KEY not set
   - Tania Gilbert (KRAKEN): KRAKEN_USER_TANIA_API_KEY not set
   - Tania Gilbert (ALPACA): ALPACA_USER_TANIA_API_KEY not set
```

---

## Advanced Troubleshooting

### Issue: Credentials Lost After Every Restart

**Diagnosis**:
```bash
# Check where credentials are being loaded from
python3 -c "
import os
print('RAILWAY_ENVIRONMENT:', os.getenv('RAILWAY_ENVIRONMENT'))
print('RENDER:', os.getenv('RENDER'))
print('.env file exists:', os.path.exists('.env'))
"
```

**If output shows**:
- `RAILWAY_ENVIRONMENT: True` → Credentials MUST be in Railway dashboard
- `RENDER: True` → Credentials MUST be in Render dashboard
- `.env file exists: True` → Credentials in .env WON'T persist in deployment

**Fix**:
- Set credentials in deployment platform UI
- Don't rely on .env file in production

### Issue: Some Credentials Work, Others Don't

**Diagnosis**:
```bash
python3 verify_credentials_persistence.py --verbose
```

**Common causes**:
1. **Typo in variable name**: `KRAKEN_USER_TANIA` vs `KRAKEN_USER_TANIA_API_KEY`
2. **Whitespace in value**: `"abc123 "` (trailing space)
3. **Wrong user_id format**: `tania` vs `tania_gilbert`

**Fix**:
- Copy variable names exactly from this document
- Trim whitespace from values
- Use correct user_id format (first_last)

### Issue: Credentials Disappear After Platform Maintenance

**Diagnosis**:
- Check platform status page
- Review deployment logs for errors
- Verify environment variables still exist in dashboard

**Prevention**:
1. **Export environment variables as backup**:

   Railway:
   ```bash
   # In Railway CLI
   railway variables
   ```

   Save output to secure location

2. **Set up monitoring alerts**:
   ```bash
   # Run credential monitor continuously
   python3 -m bot.credential_health_monitor --monitor
   ```

3. **Document credential locations**:
   - Keep secure note with credential sources
   - Document which API keys belong to which accounts
   - Track API key generation dates

---

## Prevention Checklist

Use this checklist to prevent future credential loss:

### Immediate Actions

- [ ] Run `python3 verify_credentials_persistence.py`
- [ ] Set ALL credentials in deployment platform dashboard
- [ ] Verify credentials persist after restart
- [ ] Export environment variables as backup
- [ ] Document which deployment instance is active

### Ongoing Monitoring

- [ ] Check credential health weekly: `python3 verify_credentials_persistence.py`
- [ ] Review bot logs for credential warnings
- [ ] Monitor credential health alerts in logs
- [ ] Set calendar reminder to verify credentials monthly

### Best Practices

- [ ] **NEVER** commit `.env` to git
- [ ] **ALWAYS** set credentials in deployment platform UI
- [ ] **DOCUMENT** API key rotation schedule
- [ ] **BACKUP** environment variables before platform changes
- [ ] **VERIFY** credentials after any deployment changes

---

## Quick Reference

### Check Credential Status
```bash
python3 verify_credentials_persistence.py
```

### Monitor Credentials Continuously
```bash
python3 -m bot.credential_health_monitor --monitor
```

### Set Credentials (Railway)
```
Dashboard → Service → Variables → New Variable
```

### Set Credentials (Render)
```
Dashboard → Service → Environment → Add Environment Variable
```

### Required Environment Variables

**Master Accounts** (3 exchanges):
- `COINBASE_API_KEY` + `COINBASE_API_SECRET`
- `KRAKEN_MASTER_API_KEY` + `KRAKEN_MASTER_API_SECRET`
- `ALPACA_API_KEY` + `ALPACA_API_SECRET`

**User: Daivon Frazier**:
- `KRAKEN_USER_DAIVON_API_KEY` + `KRAKEN_USER_DAIVON_API_SECRET`

**User: Tania Gilbert (Kraken)**:
- `KRAKEN_USER_TANIA_API_KEY` + `KRAKEN_USER_TANIA_API_SECRET`

**User: Tania Gilbert (Alpaca)**:
- `ALPACA_USER_TANIA_API_KEY` + `ALPACA_USER_TANIA_API_SECRET`
- `ALPACA_USER_TANIA_PAPER=true`

**Total**: 15 environment variables

---

## Success Metrics

After implementing this solution, you should:

✅ **Immediate** (< 1 hour):
- All credentials show as "✅ SET" in verification tool
- Bot successfully connects all accounts on startup
- No "NOT CONFIGURED" messages in logs

✅ **Short-term** (24 hours):
- Credentials persist through restarts
- No credential loss warnings in logs
- All accounts remain connected

✅ **Long-term** (1 week+):
- Zero credential-related disconnections
- Credentials remain stable through deployments
- Automated monitoring catches any issues early

---

## Support Resources

### New Tools (Created)
- `verify_credentials_persistence.py` - Credential verification tool
- `bot/credential_health_monitor.py` - Real-time credential monitoring

### Existing Documentation
- `KRAKEN_CONNECTION_LOST_DIAGNOSIS.md` - Previous credential issues
- `USER_CONNECTION_FIX_JAN_16_2026.md` - User enabling guide
- `.env.example` - Template for local development

### Getting Help

If credentials still get lost after following this guide:

1. **Capture diagnostics**:
   ```bash
   python3 verify_credentials_persistence.py > credential_status.txt
   ```

2. **Check bot logs**:
   ```bash
   grep "CREDENTIAL" nija.log > credential_logs.txt
   ```

3. **Export environment variables**:
   - From Railway/Render dashboard
   - Save to secure location
   - Compare before/after restart

4. **Report issue** with:
   - Deployment platform (Railway/Render)
   - Timing of credential loss
   - Steps to reproduce
   - Output from verification tool

---

## Summary

**Problem**: Credentials keep getting lost, causing recurring disconnections

**Root Cause**: Credentials not properly persisted in deployment platform

**Solution**:
1. Set credentials in deployment platform UI (not .env file)
2. Use verification tool to confirm persistence
3. Enable automatic monitoring to detect future issues

**Prevention**:
- Use new credential health monitoring (automatic)
- Run verification tool after any deployment changes
- Export environment variables as backup
- Document credential sources and rotation schedule

---

**Last Updated**: January 16, 2026  
**Status**: ✅ SOLUTION IMPLEMENTED  
**Tools Created**: 2 (verification tool + health monitor)  
**Expected Result**: Zero recurring credential loss issues
