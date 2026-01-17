# 🚨 KRAKEN TRADING SETUP REQUIRED

## Current Status

✅ **Code Configuration**: COMPLETE  
✅ **User Accounts Enabled**: YES (Daivon Frazier, Tania Gilbert)  
❌ **API Credentials**: MISSING (Required for trading)  
❌ **Trading Active**: NO (Cannot trade without credentials)

---

## What You Need to Do

NIJA is now configured to trade on Kraken for the following accounts:
- ✅ Master account (NIJA system account)
- ✅ Daivon Frazier (retail user)
- ✅ Tania Gilbert (retail user)

However, **trading cannot begin until you add Kraken API credentials** to your deployment platform.

---

## Required API Credentials

You need to set the following environment variables in Railway/Render:

### 1. Master Account (NIJA System)
```bash
KRAKEN_MASTER_API_KEY=your-master-api-key-here
KRAKEN_MASTER_API_SECRET=your-master-api-secret-here
```

### 2. Daivon Frazier Account
```bash
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret-here
```

### 3. Tania Gilbert Account
```bash
KRAKEN_USER_TANIA_API_KEY=tania-api-key-here
KRAKEN_USER_TANIA_API_SECRET=tania-api-secret-here
```

---

## How to Get Kraken API Keys

### Step 1: Log into Kraken
Go to: https://www.kraken.com/u/security/api

### Step 2: Create API Key
1. Click "Generate New Key"
2. Give it a description (e.g., "NIJA Trading Bot - Master")
3. **Set these permissions** (REQUIRED):
   - ✅ Query Funds (view balances)
   - ✅ Query Open Orders (view orders)
   - ✅ Query Closed Orders (view history)
   - ✅ Create & Modify Orders (place trades)
   - ✅ Cancel/Close Orders (cancel trades)

4. **DO NOT enable these** (SECURITY):
   - ❌ Withdraw Funds
   - ❌ Export Data
   - ❌ Access WebSockets

### Step 3: Save Credentials
1. Copy the **API Key** (looks like: `abcd1234...`)
2. Copy the **Private Key** (looks like: `xyz789...`)
3. **IMPORTANT**: Save these immediately - you cannot view them again!

### Step 4: Repeat for Each Account
- Master account needs its own API key from the master Kraken account
- Daivon needs API keys from HIS Kraken account
- Tania needs API keys from HER Kraken account

**Each person must have their own separate Kraken account.**

---

## How to Add Credentials to Railway

### For Railway Deployment:
1. Go to your Railway project: https://railway.app/
2. Select your NIJA deployment
3. Go to **Variables** tab
4. Click **+ New Variable**
5. Add each credential one at a time:
   - Variable name: `KRAKEN_MASTER_API_KEY`
   - Value: `paste-your-api-key`
6. Repeat for all 6 variables (see list above)
7. Railway will auto-restart the bot with new credentials

### For Render Deployment:
1. Go to your Render dashboard: https://render.com/
2. Select your NIJA service
3. Go to **Environment** tab
4. Click **+ Add Environment Variable**
5. Add each credential one at a time
6. Click **Save Changes**
7. Render will auto-restart the bot

---

## Verification After Setup

After adding credentials and restarting:

### Check Connection Status
```bash
python3 check_kraken_status.py
```

Expected output:
```
✅ Master account: Connected to Kraken
✅ User #1 (Daivon Frazier): Connected to Kraken
✅ User #2 (Tania Gilbert): Connected to Kraken
```

### Monitor Logs
Look for these messages in your deployment logs:
```
✅ MASTER: Connected to Kraken (Balance: $XXX.XX)
✅ USER: Daivon Frazier: Connected to Kraken (Balance: $XXX.XX)
✅ USER: Tania Gilbert: Connected to Kraken (Balance: $XXX.XX)
🔍 Scanning Kraken markets for opportunities...
```

---

## Troubleshooting

### "Connection Failed" Error
**Cause**: Invalid or missing API credentials  
**Fix**: Double-check credentials in Railway/Render match Kraken API keys exactly

### "Permission Denied" Error
**Cause**: API key doesn't have required permissions  
**Fix**: Recreate API key with correct permissions (see Step 2 above)

### "Invalid Nonce" Error
**Cause**: API key was used recently, bot restarted too quickly  
**Fix**: Wait 60 seconds and restart deployment (this is automatic)

### Still Not Trading After Setup
**Check these**:
1. Are all 6 environment variables set? (Run `python3 check_kraken_status.py`)
2. Do accounts have sufficient balance? (Minimum $25 recommended)
3. Are API keys from the correct accounts? (Master from master, Daivon from Daivon's account)
4. Did the bot restart after adding credentials?

---

## Important Security Notes

🔒 **NEVER** commit API keys to Git or share them publicly  
🔒 **NEVER** enable "Withdraw Funds" permission on API keys  
🔒 Each API key should only be used by ONE bot instance  
🔒 Store credentials ONLY in Railway/Render environment variables  
🔒 Regenerate API keys immediately if compromised  

---

## What Happens When Trading Starts

Once credentials are configured, NIJA will:

1. **Connect to Kraken** for each account (Master, Daivon, Tania)
2. **Scan Kraken markets** every 2.5 minutes (730+ crypto pairs)
3. **Execute trades** using the dual RSI strategy (RSI_9 + RSI_14)
4. **Manage positions** independently for each account
5. **Exit losing trades** within 30 minutes (NIJA is for profit!)
6. **Take profits** at 1.5%, 1.2%, or 1.0% targets

---

## Next Steps

- [ ] Get Kraken API keys for Master account
- [ ] Get Kraken API keys for Daivon Frazier account  
- [ ] Get Kraken API keys for Tania Gilbert account
- [ ] Add all 6 environment variables to Railway/Render
- [ ] Wait for automatic restart (2-5 minutes)
- [ ] Verify connections: `python3 check_kraken_status.py`
- [ ] Monitor logs for first trades

---

## Additional Documentation

- **Kraken Quick Start**: [KRAKEN_QUICK_START.md](KRAKEN_QUICK_START.md)
- **Multi-Exchange Trading**: [MULTI_EXCHANGE_TRADING_GUIDE.md](MULTI_EXCHANGE_TRADING_GUIDE.md)
- **User Setup Guide**: [USER_SETUP_GUIDE.md](USER_SETUP_GUIDE.md)
- **Kraken API Docs**: https://docs.kraken.com/rest/

---

**Status**: ✅ Code ready, ❌ API credentials required  
**Last Updated**: January 17, 2026  
**Branch**: `copilot/make-trade-on-accounts`
