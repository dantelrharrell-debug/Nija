# Solution: Master Kraken Account Not Trading

## Problem Summary

**Issue**: Master Kraken account is not connecting and trading, even though USER Kraken accounts (daivon_frazier, tania_gilbert) ARE successfully connected and trading.

**Current Status** (from logs):
- ✅ USER Kraken accounts ARE connected and trading:
  - daivon_frazier_kraken: $30.00
  - tania_gilbert_kraken: $73.21
- ❌ MASTER Kraken account is NOT connected
- ✅ MASTER Coinbase IS connected: $0.76

**Expected Status**:
- ✅ MASTER Kraken should be connected and trading independently
- ✅ USER Kraken accounts should continue trading (already working)
- ✅ MASTER Coinbase should continue trading (already working)

---

## Root Cause Analysis

### Why USER Kraken Works But MASTER Doesn't

The bot uses different environment variables for MASTER vs USER accounts:

**MASTER Account Credentials**:
```bash
KRAKEN_MASTER_API_KEY=<master-api-key>
KRAKEN_MASTER_API_SECRET=<master-api-secret>
```

**USER Account Credentials** (for daivon_frazier):
```bash
KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>
```

**USER Account Credentials** (for tania_gilbert):
```bash
KRAKEN_USER_TANIA_API_KEY=<tania-api-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>
```

### The Problem

Looking at the logs, USER accounts ARE connecting, which means:
- `KRAKEN_USER_DAIVON_*` credentials ARE set ✅
- `KRAKEN_USER_TANIA_*` credentials ARE set ✅
- `KRAKEN_MASTER_*` credentials are either:
  - ❌ NOT set at all, OR
  - ❌ Set but invalid/malformed, OR
  - ❌ Set but with insufficient permissions

---

## Solution Steps

### Step 1: Run Diagnostic Script

First, identify the exact issue:

```bash
python3 diagnose_master_kraken_live.py
```

This will tell you:
1. ✅/❌ Whether MASTER credentials are set
2. ✅/❌ Whether they're valid (not whitespace)
3. ✅/❌ Whether the connection succeeds
4. ⚠️  The specific error if it fails

### Step 2: Fix Based on Diagnostic Results

#### Scenario A: Credentials NOT SET

**Diagnostic Output**:
```
❌ KRAKEN_MASTER_API_KEY: NOT SET
❌ KRAKEN_MASTER_API_SECRET: NOT SET
```

**Solution**: Add MASTER Kraken credentials

1. **Get Kraken API Credentials**:
   - Go to: https://www.kraken.com/u/security/api
   - Click "Generate New Key"
   - Set description: "NIJA Master Trading Bot"
   - Enable these permissions:
     - ✅ Query Funds
     - ✅ Query Open Orders & Trades
     - ✅ Query Closed Orders & Trades
     - ✅ Create & Modify Orders
     - ✅ Cancel/Close Orders
     - ❌ Do NOT enable: Withdraw Funds (security risk)
   - Click "Generate Key"
   - Copy the API Key and Private Key

2. **Add to Railway** (if using Railway):
   ```bash
   # In Railway Dashboard:
   # 1. Select your service
   # 2. Click "Variables" tab
   # 3. Add these variables:
   
   KRAKEN_MASTER_API_KEY=<your-api-key-here>
   KRAKEN_MASTER_API_SECRET=<your-private-key-here>
   
   # 4. Click "Save" (Railway will auto-restart)
   ```

3. **Add to Render** (if using Render):
   ```bash
   # In Render Dashboard:
   # 1. Select your service
   # 2. Click "Environment" tab
   # 3. Add these variables:
   
   KRAKEN_MASTER_API_KEY=<your-api-key-here>
   KRAKEN_MASTER_API_SECRET=<your-private-key-here>
   
   # 4. Click "Save Changes"
   # 5. Click "Manual Deploy" → "Deploy latest commit"
   ```

#### Scenario B: Credentials SET but MALFORMED

**Diagnostic Output**:
```
❌ KRAKEN_MASTER_API_KEY: SET but has leading/trailing whitespace
   OR
❌ KRAKEN_MASTER_API_SECRET: SET but contains ONLY whitespace
```

**Solution**: Fix whitespace issues

1. In your deployment platform (Railway/Render):
   - Select the service
   - Go to Variables/Environment tab
   - Find `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`
   - **Carefully** remove any:
     - Leading spaces
     - Trailing spaces
     - Newlines
     - Tabs
   - The value should be ONLY the API key/secret, nothing else
   - Save and restart

#### Scenario C: Connection FAILS with Permission Error

**Diagnostic Output**:
```
❌ CONNECTION FAILED
Error: Permission denied
```

**Solution**: Enable required permissions

1. Go to: https://www.kraken.com/u/security/api
2. Find your MASTER API key
3. Click "Edit"
4. Enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
5. Save
6. Wait 1-2 minutes for changes to propagate
7. Restart the bot

#### Scenario D: Connection FAILS with Nonce Error

**Diagnostic Output**:
```
❌ CONNECTION FAILED
Error: Invalid nonce
```

**Solution**: Wait and retry

1. Wait 1-2 minutes
2. Restart the bot
3. If issue persists:
   - The API key may be in a "locked" state
   - Solution: Generate a new API key (Step 2A above)
   - Update environment variables
   - Restart

#### Scenario E: Connection FAILS with Invalid Signature

**Diagnostic Output**:
```
❌ CONNECTION FAILED
Error: Invalid signature
```

**Solution**: Regenerate credentials

1. The API key or secret is incorrect/corrupted
2. Generate a new API key (Step 2A above)
3. Update environment variables with NEW credentials
4. Restart the bot

---

## Verification

After fixing, check that MASTER Kraken connects:

### 1. Run Diagnostic Again

```bash
python3 diagnose_master_kraken_live.py
```

**Expected Output**:
```
✅ KRAKEN_MASTER_API_KEY: SET (56 chars)
✅ KRAKEN_MASTER_API_SECRET: SET (88 chars)
✅ Will use MASTER credentials
✅ MASTER KRAKEN CONNECTED SUCCESSFULLY!
💰 Account Balance: $XXX.XX USD
✅ Account is FUNDED and ready to trade
```

### 2. Check Bot Startup Logs

After restarting the bot, look for these messages:

**Connection Phase**:
```
📊 Attempting to connect Kraken Pro (MASTER)...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
```

**Funding Detection**:
```
🔍 Detecting funded brokers...
   💰 kraken: $XXX.XX
      ✅ FUNDED - Ready to trade
```

**Thread Startup**:
```
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING
🔷 STARTING MASTER BROKER THREADS
✅ Started independent trading thread for kraken (MASTER)
```

### 3. Expected Final State

After successful fix, you should have **3 independent trading threads**:

**MASTER Accounts**:
- ✅ Coinbase: $0.76 (already working)
- ✅ Kraken: $XXX.XX (newly fixed)

**USER Accounts**:
- ✅ daivon_frazier_kraken: $30.00 (already working)
- ✅ tania_gilbert_kraken: $73.21 (already working)

**Total**: 4 accounts, 3 different Kraken accounts (1 MASTER + 2 USERS)

---

## Understanding Master vs User Architecture

### Master Account (NIJA System)
- **Purpose**: The bot's own trading capital
- **Credentials**: `KRAKEN_MASTER_API_KEY` / `KRAKEN_MASTER_API_SECRET`
- **Trading**: Independent, controlled by NIJA strategy
- **Profits**: Belong to NIJA/system owner

### User Accounts (Investors/Clients)
- **Purpose**: Individual investor capital
- **Credentials**: `KRAKEN_USER_{NAME}_API_KEY` / `KRAKEN_USER_{NAME}_API_SECRET`
- **Trading**: Independent, each user trades separately
- **Profits**: Belong to the individual user

### Why Both?

The architecture allows:
1. **NIJA** to trade its own capital (MASTER)
2. **Investors** to have NIJA trade their capital (USERS)
3. **Complete isolation** - failures in one don't affect others
4. **Separate accounting** - each account's P&L is independent

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Using Same Credentials for MASTER and USER

**WRONG**:
```bash
KRAKEN_MASTER_API_KEY="abc123xyz"
KRAKEN_USER_DAIVON_API_KEY="abc123xyz"  # Same as MASTER
```

**Result**: Nonce conflicts, both accounts fail intermittently

**FIX**: Create separate API keys for MASTER and each USER

### ❌ Mistake 2: Copy/Paste with Hidden Characters

**WRONG**:
```bash
# Has invisible newline at end
KRAKEN_MASTER_API_SECRET="xyz789secret
"
```

**Result**: "Credentials contain only whitespace" error

**FIX**: Carefully paste without extra spaces/newlines

### ❌ Mistake 3: Insufficient Permissions

**WRONG**: Creating API key with only "Query Funds" permission

**Result**: Connection succeeds but trading fails with "Permission denied"

**FIX**: Enable ALL required trading permissions (see Step 2A)

### ❌ Mistake 4: Not Restarting After Changes

**WRONG**: Updating environment variables but not restarting

**Result**: Old (missing) credentials still in use

**FIX**: Always restart deployment after environment variable changes

---

## Alternative: Disable Master Kraken

If you DON'T want a separate MASTER Kraken account, you can simply:

1. **Do Nothing** - don't set KRAKEN_MASTER_* variables
2. The bot will continue trading with:
   - MASTER Coinbase
   - USER Kraken accounts (daivon, tania)
3. This is a valid configuration

**When to use this**:
- You only want users to trade on Kraken
- You only want NIJA system to trade on Coinbase
- You don't have separate capital for a MASTER Kraken account

---

## Quick Reference

### Check Credential Status
```bash
python3 diagnose_master_kraken_live.py
```

### View All Environment Variables
```bash
python3 validate_all_env_vars.py
```

### Test Kraken Connection
```bash
python3 test_kraken_connection_live.py
```

### Check Trading Status
```bash
python3 check_trading_status.py
```

### Watch Live Logs (filter for Kraken)
```bash
tail -f nija.log | grep -E "Kraken|MASTER|kraken"
```

---

## Still Having Issues?

If MASTER Kraken still won't connect after following all steps:

### 1. Check Kraken API Status
- Visit: https://status.kraken.com
- Verify API is operational

### 2. Verify System Time
```bash
date
# Should match actual time
```
- Kraken requires accurate time for nonce validation
- If time is wrong, fix system clock/NTP

### 3. Review Full Error Logs
```bash
# Get detailed error context
grep -A 20 "Kraken MASTER" nija.log
```

### 4. Try Fresh API Key
- Sometimes API keys get into a bad state
- Generate a completely new key
- Update environment variables
- Restart

### 5. Contact Support
If all else fails, provide:
- Output of `diagnose_master_kraken_live.py`
- Startup logs (first 100 lines)
- Error messages from Kraken connection attempt

---

## Summary

**Problem**: MASTER Kraken not connecting while USER Kraken accounts work fine

**Most Likely Cause**: KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET are not set in your deployment platform (Railway/Render)

**Solution**:
1. Run `python3 diagnose_master_kraken_live.py` to confirm
2. Create MASTER Kraken API key with proper permissions
3. Add credentials to deployment platform environment variables
4. Restart the bot
5. Verify "✅ Kraken MASTER connected" appears in logs

**Expected Outcome**: 2 MASTER accounts + 2 USER accounts = 4 independent trading threads

---

**Last Updated**: January 16, 2026  
**Status**: Solution documented, diagnostic script created  
**Next Step**: User must set KRAKEN_MASTER_* credentials in deployment platform
