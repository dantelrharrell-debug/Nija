# Kraken Multi-User Deployment Guide

**Date**: January 11, 2026  
**Status**: ✅ Ready for Deployment  
**Purpose**: Enable Kraken trading for Master account and all user accounts

---

## Overview

This guide enables Kraken Pro trading for:
- ✅ **Master Account** - System trading account
- ✅ **User #1 (Daivon Frazier)** - Individual user account
- ✅ **User #2 (Tania Gilbert)** - Individual user account

All three accounts trade independently on Kraken Pro with separate balances, positions, and risk limits.

---

## Prerequisites

### 1. Kraken API Keys

You need API keys for each account. Get them from: https://www.kraken.com/u/security/api

**Required Permissions** (for each API key):
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders

### 2. Account Funding

Each Kraken account needs funding to trade:
- **Minimum**: $1.00 (will allow trading but fees may consume profits)
- **Recommended**: $25.00+ per account for better profitability

### 3. Environment Variables

The following environment variables must be set:

```bash
# Master Account
KRAKEN_MASTER_API_KEY=<your_master_api_key>
KRAKEN_MASTER_API_SECRET=<your_master_api_secret>

# User #1 (Daivon Frazier)
KRAKEN_USER_DAIVON_API_KEY=<daivon_api_key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon_api_secret>

# User #2 (Tania Gilbert)
KRAKEN_USER_TANIA_API_KEY=<tania_api_key>
KRAKEN_USER_TANIA_API_SECRET=<tania_api_secret>
```

---

## Deployment Steps

### Option A: Railway Deployment

1. **Go to your Railway project**: https://railway.app
2. **Open your service** (e.g., "nija-trading-bot")
3. **Click "Variables" tab**
4. **Add the following variables**:
   ```
   KRAKEN_MASTER_API_KEY = <paste your key>
   KRAKEN_MASTER_API_SECRET = <paste your secret>
   KRAKEN_USER_DAIVON_API_KEY = <paste key>
   KRAKEN_USER_DAIVON_API_SECRET = <paste secret>
   KRAKEN_USER_TANIA_API_KEY = <paste key>
   KRAKEN_USER_TANIA_API_SECRET = <paste secret>
   ```
5. **Click "Deploy"** to restart with new variables

### Option B: Render Deployment

1. **Go to Render Dashboard**: https://dashboard.render.com
2. **Open your web service**
3. **Click "Environment" tab**
4. **Add environment variables** (same as Railway above)
5. **Service will auto-deploy** after saving

### Option C: Local Development

1. **Copy credentials to `.env` file**:
   ```bash
   cd /path/to/Nija
   nano .env  # or use your preferred editor
   ```

2. **Add the variables** (same as above)

3. **Start the bot**:
   ```bash
   ./start.sh
   ```

---

## Verification

### Step 1: Check Logs for Connection Messages

After deploying, check the startup logs for:

```
======================================================================
👤 CONNECTING USER ACCOUNTS
======================================================================
📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $XXX.XX

📊 Attempting to connect User #2 (Tania Gilbert) - Kraken...
   ✅ User #2 Kraken connected
   💰 User #2 Kraken balance: $XXX.XX

======================================================================
📊 ACCOUNT TRADING STATUS SUMMARY
======================================================================
✅ MASTER ACCOUNT: TRADING (Broker: kraken)
✅ USER #1 (Daivon Frazier): TRADING (Broker: Kraken)
✅ USER #2 (Tania Gilbert): TRADING (Broker: Kraken)
======================================================================
```

### Step 2: Run Test Script (Local Only)

If running locally, you can test connections:

```bash
python3 test_kraken_connections.py
```

Expected output:
```
🔍 KRAKEN CONNECTION TEST - MASTER + ALL USERS
✅ Master account: CONNECTED
✅ User #1 (Daivon): CONNECTED
✅ User #2 (Tania): CONNECTED
🎉 ALL ACCOUNTS CONNECTED - Ready for multi-account trading!
```

### Step 3: Monitor Trading Activity

Look for trading cycle logs:
```
🔄 kraken (MASTER) - Cycle #1
🔄 kraken (USER:daivon_frazier) - Cycle #1
🔄 kraken (USER:tania_gilbert) - Cycle #1
```

---

## Troubleshooting

### Issue: "Kraken credentials not configured"

**Cause**: Environment variables not set or misspelled

**Solution**:
1. Check variable names match exactly (case-sensitive)
2. Verify no extra spaces in keys/secrets
3. Restart service after adding variables

### Issue: "Kraken connection failed"

**Cause**: Invalid API keys or wrong permissions

**Solution**:
1. Verify API key permissions in Kraken dashboard
2. Check that keys are from correct Kraken account
3. Ensure API keys are not expired

### Issue: "Permission denied" or "Invalid key"

**Cause**: API key missing required permissions

**Solution**:
1. Go to Kraken.com → Security → API
2. Edit the API key
3. Enable all required permissions (see Prerequisites)
4. Save and update environment variables

### Issue: User #1 or #2 shows "NOT TRADING"

**Cause**: Credentials not set or connection failed

**Solution**:
1. Check logs for specific error message
2. Verify user-specific credentials are set:
   - User #1: `KRAKEN_USER_DAIVON_API_KEY` / `KRAKEN_USER_DAIVON_API_SECRET`
   - User #2: `KRAKEN_USER_TANIA_API_KEY` / `KRAKEN_USER_TANIA_API_SECRET`
3. Check that user ID matches exactly: `daivon_frazier` and `tania_gilbert`

### Issue: "No balance" or zero balance

**Cause**: Kraken account not funded

**Solution**:
1. Log into Kraken account
2. Deposit funds (minimum $1.00, recommended $25+)
3. Wait for deposit to confirm
4. Restart bot

---

## Trading Configuration

### Independent Trading

Each account trades completely independently:
- **Master Account**: Uses master strategy and risk limits
- **User #1**: Uses user-specific limits (defined in user config)
- **User #2**: Uses user-specific limits (defined in user config)

### Position Limits

- **Master**: 8 positions max (configured in trading strategy)
- **User #1**: 7 positions max (from user config)
- **User #2**: 7 positions max (from user config)

### Risk Management

- Each account has independent stop losses
- Each account has independent profit targets
- Losses in one account don't affect others
- All accounts use APEX v7.1 strategy

---

## Architecture Details

### Credential Format

The bot uses a specific naming convention for user credentials:

```
KRAKEN_USER_{FIRSTNAME}_API_KEY
KRAKEN_USER_{FIRSTNAME}_API_SECRET
```

Where `{FIRSTNAME}` is the first part of the user ID (uppercase):
- `daivon_frazier` → `DAIVON`
- `tania_gilbert` → `TANIA`

### Code Location

User connections are established in:
- **File**: `bot/trading_strategy.py`
- **Lines**: ~299-354 (User account connection section)

### Multi-Account Manager

The `MultiAccountBrokerManager` class handles:
- Separate broker instances per user
- Independent balance tracking
- Isolated position management
- User-specific trading threads

---

## Expected Behavior

### On Startup

1. Bot connects to Master Kraken account
2. Bot connects to User #1 Kraken account
3. Bot connects to User #2 Kraken account
4. Each connection shows balance
5. Status summary shows all three accounts

### During Trading

1. Each account scans markets independently
2. Each account executes trades based on APEX v7.1 strategy
3. Each account manages its own positions
4. Trading cycles log activity per account

### Independent Failures

If one account fails:
- Other accounts continue trading normally
- Failed account shows error in logs
- Bot remains operational for connected accounts

---

## Security Notes

✅ **API credentials are never logged** (only length is shown)  
✅ **Credentials are encrypted** before storage  
✅ **API keys are not committed to git** (in `.gitignore`)  
✅ **Trade-only mode enabled** for user accounts  
✅ **Position size limits enforced** per user  
✅ **Daily loss limits enforced** per user

---

## Support

For issues or questions:
1. Check logs for specific error messages
2. Review this troubleshooting guide
3. Verify all environment variables are set correctly
4. Ensure Kraken API key permissions are correct
5. Confirm Kraken accounts are funded

---

## Related Documentation

- `USER_SETUP_COMPLETE_DAIVON.md` - User #1 setup details
- `USER_SETUP_COMPLETE_TANIA.md` - User #2 setup details
- `KRAKEN_MULTI_ACCOUNT_GUIDE.md` - Kraken account setup guide
- `MULTI_USER_SETUP_GUIDE.md` - Multi-user system guide
- `ENVIRONMENT_VARIABLES_GUIDE.md` - All environment variables

---

**Deployment Status**: ✅ Ready  
**Last Updated**: January 11, 2026  
**Next Review**: After first successful deployment
