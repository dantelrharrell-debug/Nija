# QUICK FIX: Recurring Disconnections

## Problem
"Master and all users are disconnected again - why does this keep happening?"

## Immediate Solution

### Step 1: Check What's Wrong
```bash
python3 verify_credentials_persistence.py
```

This will show you:
- ✅ Which credentials are set
- ❌ Which credentials are missing
- 📋 Exact commands to fix it

### Step 2: Set Credentials in Deployment Platform

**If using Railway**:
1. Go to https://railway.app/
2. Select your NIJA service
3. Click **Variables** tab
4. Add missing credentials shown by the tool
5. Click **Save** (auto-redeploys)

**If using Render**:
1. Go to https://render.com/
2. Select your NIJA service  
3. Click **Environment** tab
4. Add missing credentials
5. Click **Save Changes**
6. Manual Deploy → Deploy latest commit

### Step 3: Verify Fix
After deployment completes, run again:
```bash
python3 verify_credentials_persistence.py
```

Should show: `✅ SUCCESS: All configured accounts have valid credentials`

## Why This Keeps Happening

Credentials are **NOT PERSISTED** because:
- ❌ Set in `.env` file (doesn't deploy to production)
- ❌ Set in shell session (lost on restart)
- ✅ MUST be set in deployment platform dashboard

## Prevention

The bot now monitors credentials automatically:
- Checks every 5 minutes
- Alerts when credentials disappear
- Logs exactly when/what was lost

## Required Environment Variables

**For each user account to work, you need**:

**Daivon Frazier (Kraken)**:
```
KRAKEN_USER_DAIVON_API_KEY=<key>
KRAKEN_USER_DAIVON_API_SECRET=<secret>
```

**Tania Gilbert (Kraken)**:
```
KRAKEN_USER_TANIA_API_KEY=<key>
KRAKEN_USER_TANIA_API_SECRET=<secret>
```

**Tania Gilbert (Alpaca)**:
```
ALPACA_USER_TANIA_API_KEY=<key>
ALPACA_USER_TANIA_API_SECRET=<secret>
ALPACA_USER_TANIA_PAPER=true
```

## Get Detailed Help

Read the complete guide:
```bash
cat RECURRING_DISCONNECTION_SOLUTION_JAN_16_2026.md
```

Or open it in a text editor/browser.

## Still Having Issues?

1. Check deployment platform environment variables
2. Verify no typos in variable names
3. Confirm values don't have extra spaces
4. Export variables as backup before changes
5. Compare before/after restart

## Success Criteria

✅ All enabled users show "✅ TRADING" in logs  
✅ No "NOT CONFIGURED" warnings  
✅ Credentials persist through restarts  
✅ Zero credential loss warnings in logs
