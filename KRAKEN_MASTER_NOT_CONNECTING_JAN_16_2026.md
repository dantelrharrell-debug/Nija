# Kraken Master Not Connecting - Solution Guide (Jan 16, 2026)

## Issue Summary

**Problem**: Kraken Master credentials are detected but the master account is not connecting and trading.

**Evidence from Logs**:
```
✅ Kraken Master credentials detected
...
WARNING | ⚠️  Expected but NOT Connected:
WARNING |    ❌ KRAKEN
```

**Meanwhile**:
```
INFO | 💰 Kraken Balance (USER:tania_gilbert): USD $73.21 + USDT $0.00 = $73.21
INFO |    💰 User: tania_gilbert | kraken: $73.21
INFO |       ✅ FUNDED - Ready to trade
```

**Current State**:
- ✅ User Kraken account (tania_gilbert) IS connected and trading
- ❌ Master Kraken account IS NOT connected
- ✅ Coinbase master IS connected ($0.76)
- Result: Only 1 exchange trading (Coinbase) instead of 2 (Coinbase + Kraken)

---

## Root Causes

### 1. Architectural Bug (FIXED)

**Issue**: The `IndependentBrokerTrader` class was checking the wrong broker source.

**Details**:
- Master brokers are stored in: `multi_account_manager.master_brokers`
- But detection was using: `broker_manager.brokers` (old system)
- This could prevent detection even if master Kraken HAD connected

**Fix Applied**: Updated three methods to use correct source:
- `detect_funded_brokers()` 
- `start_independent_trading()`
- `get_status_summary()`

**Status**: ✅ FIXED in commit b935d2b

### 2. Master Credentials Issue (PRIMARY CAUSE)

**Issue**: Master Kraken credentials are set but failing to connect.

**Possible Causes**:

#### A. Invalid or Incorrect Credentials
The API key/secret may be:
- From a different Kraken account
- Expired or regenerated
- Copy/pasted incorrectly with invisible characters
- Test/sandbox credentials (Kraken uses production API only)

#### B. Insufficient API Permissions
The master API key may lack required permissions. User account works because it has correct permissions.

**Required Permissions**:
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders

#### C. Whitespace in Credentials
Environment variables may contain invisible spaces/newlines:
```bash
# WRONG (has trailing newline)
KRAKEN_MASTER_API_KEY="abc123
"

# CORRECT
KRAKEN_MASTER_API_KEY="abc123"
```

#### D. Using User Credentials for Master
The master environment variables might accidentally contain user credentials:
```bash
# WRONG (tania's credentials in master vars)
KRAKEN_MASTER_API_KEY="<tania's key>"
KRAKEN_MASTER_API_SECRET="<tania's secret>"

# CORRECT (separate master account)
KRAKEN_MASTER_API_KEY="<master account key>"
KRAKEN_MASTER_API_SECRET="<master account secret>"
```

---

## Solution Steps

### Step 1: Verify Current Credential Configuration

Run the diagnostic script:
```bash
python3 diagnose_master_kraken_issue.py
```

This will show:
- Which credentials are set
- Which have whitespace issues
- Whether master can connect
- Specific error messages

### Step 2: Check Kraken API Key Settings

1. Log in to Kraken: https://www.kraken.com/u/security/api
2. Find the API key used for MASTER account
3. Verify it has all required permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable: Withdraw Funds (security risk)

### Step 3: Update Master Credentials

#### For Railway:
1. Go to Railway dashboard
2. Select your service
3. Click "Variables" tab
4. Update or add:
   ```
   KRAKEN_MASTER_API_KEY=<your-master-api-key>
   KRAKEN_MASTER_API_SECRET=<your-master-api-secret>
   ```
5. **Important**: Remove any leading/trailing spaces or newlines
6. Click "Save"
7. Railway will auto-restart

#### For Render:
1. Go to Render dashboard
2. Select your service
3. Click "Environment" tab
4. Update or add:
   ```
   KRAKEN_MASTER_API_KEY=<your-master-api-key>
   KRAKEN_MASTER_API_SECRET=<your-master-api-secret>
   ```
5. **Important**: Remove any leading/trailing spaces or newlines
6. Click "Save Changes"
7. Click "Manual Deploy" → "Deploy latest commit"

### Step 4: Verify Fix

After restarting, check logs for:

**Success indicators**:
```
✅ Kraken Master credentials detected
...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
...
🔍 Detecting funded brokers...
   💰 kraken: $XX.XX
      ✅ FUNDED - Ready to trade
```

**If still failing**:
```
⚠️  Kraken MASTER connection failed
```

Check for specific errors:
- "Permission denied" → Fix API key permissions (Step 2)
- "Invalid nonce" → Wait 1-2 minutes and restart
- "Invalid signature" → Credentials are incorrect, regenerate API key
- "Credentials contain only whitespace" → Remove spaces/newlines (Step 3)

---

## Alternative: Use Only User Accounts

If you don't want a separate master Kraken account, you can:

1. **Option A**: Remove master credentials entirely
   ```bash
   # In Railway/Render, delete these variables:
   KRAKEN_MASTER_API_KEY
   KRAKEN_MASTER_API_SECRET
   ```
   
   Result: Users trade independently, no master Kraken trading

2. **Option B**: Use user account AS master (not recommended)
   - This creates confusion between master and user roles
   - Better to either have distinct master account OR user-only trading

---

## Understanding Master vs User Architecture

### Master Account
- **Purpose**: Nija system's own trading account
- **Credentials**: `KRAKEN_MASTER_API_KEY` / `KRAKEN_MASTER_API_SECRET`
- **Trading**: Independent from user accounts
- **Balance**: Separate from user balances

### User Accounts  
- **Purpose**: Individual investor/client accounts
- **Credentials**: `KRAKEN_USER_{NAME}_API_KEY` / `KRAKEN_USER_{NAME}_API_SECRET`
- **Trading**: Each user trades independently
- **Balance**: Separate per user

### Current Setup (from logs)
```
Master Accounts:
├─ Coinbase: $0.76 (connected, trading)
└─ Kraken: NOT CONNECTED ❌

User Accounts:
└─ tania_gilbert (Kraken): $73.21 (connected, trading)
```

### Desired Setup
```
Master Accounts:
├─ Coinbase: $0.76 (connected, trading)
└─ Kraken: $XX.XX (connected, trading) ← FIX THIS

User Accounts:
└─ tania_gilbert (Kraken): $73.21 (connected, trading)
```

---

## Quick Diagnosis Commands

```bash
# Check environment variables
python3 diagnose_master_kraken_issue.py

# Verify all credentials
python3 validate_all_env_vars.py

# Test Kraken connection
python3 test_kraken_connection_live.py

# Check trading status
python3 check_trading_status.py

# Watch live logs
tail -f nija.log | grep -E "Kraken|MASTER|FUNDED"
```

---

## Common Mistakes

### ❌ Mistake 1: Using Same Credentials for Master and User
```bash
# WRONG - Same key for both
KRAKEN_MASTER_API_KEY="abc123"
KRAKEN_USER_TANIA_API_KEY="abc123"  # Same as master
```

**Result**: Nonce conflicts, both fail intermittently

**Fix**: Create separate API keys for master and each user

### ❌ Mistake 2: Copy/Paste with Extra Characters
```bash
# WRONG - Has invisible newline at end
KRAKEN_MASTER_API_SECRET="xyz789
"
```

**Result**: "Credentials contain only whitespace" error

**Fix**: Carefully paste without extra spaces/newlines

### ❌ Mistake 3: Insufficient Permissions
Creating API key with only "Query Funds" permission.

**Result**: "Permission denied" error when trying to trade

**Fix**: Enable all required trading permissions

### ❌ Mistake 4: Not Restarting After Changes
Updating environment variables but not restarting deployment.

**Result**: Old credentials still in use

**Fix**: Always restart after environment variable changes

---

## Testing Your Fix

### 1. Check Credentials Are Loaded
```bash
python3 -c "
import os
key = os.getenv('KRAKEN_MASTER_API_KEY', '')
secret = os.getenv('KRAKEN_MASTER_API_SECRET', '')
print(f'Master Key: {\"SET\" if key else \"NOT SET\"} ({len(key)} chars)')
print(f'Master Secret: {\"SET\" if secret else \"NOT SET\"} ({len(secret)} chars)')
"
```

Expected: Both SET with reasonable lengths (50-100 chars)

### 2. Test Connection
```bash
python3 diagnose_master_kraken_issue.py
```

Expected: "✅ MASTER KRAKEN CONNECTED!"

### 3. Check Bot Logs
```bash
tail -f nija.log
```

Expected sequence:
```
✅ Kraken Master credentials detected
📊 Attempting to connect Kraken Pro (MASTER)...
✅ Kraken MASTER connected
🔍 Detecting funded brokers...
   💰 kraken: $XX.XX
      ✅ FUNDED - Ready to trade
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING
🔷 STARTING MASTER BROKER THREADS
✅ Started independent trading thread for kraken (MASTER)
```

---

## Expected Outcome

After fixing master credentials, you should see:

**2 master exchanges trading**:
- Coinbase Master: $0.76
- Kraken Master: $XX.XX (your balance)

**1 user account trading**:
- tania_gilbert (Kraken): $73.21

**Total**: 3 independent trading threads
- 2 master threads (Coinbase, Kraken)
- 1 user thread (tania_gilbert on Kraken)

---

## Support Resources

- **This guide**: Complete troubleshooting for master Kraken
- **KRAKEN_CONNECTION_TROUBLESHOOTING.md**: General Kraken connection issues
- **MASTER_BROKER_ARCHITECTURE.md**: Understanding master vs user architecture
- **MULTI_EXCHANGE_TRADING_GUIDE.md**: Setting up multiple exchanges
- **diagnose_master_kraken_issue.py**: Diagnostic script (run this first!)

---

## Status Checklist

After following this guide, verify:

- [ ] Ran `python3 diagnose_master_kraken_issue.py`
- [ ] Verified master credentials are SET and not malformed
- [ ] Checked API key permissions on Kraken website
- [ ] Updated/fixed credentials in Railway/Render
- [ ] Restarted deployment
- [ ] Confirmed "✅ Kraken MASTER connected" in logs
- [ ] Confirmed "✅ FUNDED - Ready to trade" for master Kraken
- [ ] Confirmed master Kraken trading thread started
- [ ] Saw master Kraken executing trades

---

## Still Having Issues?

If master Kraken still won't connect after following all steps:

1. **Generate a new API key** on Kraken website
   - Sometimes keys get corrupted or rate-limited
   - Fresh key = fresh start

2. **Check Kraken API status**: https://status.kraken.com
   - API might be experiencing issues

3. **Try user-only mode** (disable master Kraken temporarily)
   - Remove KRAKEN_MASTER_* variables
   - Keep user accounts active
   - Verify users still trade

4. **Check system time synchronization**
   ```bash
   date
   # Should match actual time
   ```
   - Kraken requires accurate system time for nonce validation

5. **Review full error logs**
   ```bash
   grep -A 10 "Kraken MASTER" nija.log
   ```
   - Look for specific error messages

---

**Last Updated**: January 16, 2026  
**Issue**: Kraken master credentials detected but not connecting  
**Status**: Solution provided, awaiting user credential verification
