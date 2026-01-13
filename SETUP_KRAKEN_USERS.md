# Kraken User Account Setup Guide

## Problem
Users Daivon Frazier and Tania Gilbert showing "NOT TRADING (Connection failed or not configured)" because their Kraken API credentials are not set in the environment.

## Quick Fix

### Step 1: Verify Current Status

Run the verification script to check which credentials are missing:

```bash
python3 verify_kraken_users.py
```

### Step 2: Get Kraken API Credentials

For each user account (Daivon Frazier and Tania Gilbert), you need to:

1. **Log in to Kraken**: https://www.kraken.com/
2. **Navigate to API Settings**: https://www.kraken.com/u/security/api
3. **Create a New API Key** with these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. **Save the API Key and Private Key** (you won't be able to see the private key again)

**Important**: Create separate API keys for each user account.

### Step 3: Add Environment Variables

You need to add **6 environment variables total**:

#### For Master Account (NIJA System)
```
KRAKEN_MASTER_API_KEY=<master-api-key-here>
KRAKEN_MASTER_API_SECRET=<master-private-key-here>
```

#### For User #1 (Daivon Frazier)
```
KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key-here>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-private-key-here>
```

#### For User #2 (Tania Gilbert)
```
KRAKEN_USER_TANIA_API_KEY=<tania-api-key-here>
KRAKEN_USER_TANIA_API_SECRET=<tania-private-key-here>
```

## Deployment Platform Instructions

### Railway

1. **Open your Railway project**: https://railway.app
2. **Go to your NIJA service**
3. **Click on "Variables" tab**
4. **Click "New Variable" for each credential**:
   - Variable Name: `KRAKEN_MASTER_API_KEY`
   - Value: [paste your master API key]
   - Click "Add"
5. **Repeat for all 6 variables** (see list above)
6. **Railway will automatically redeploy** your service with the new variables

### Render

1. **Open your Render dashboard**: https://dashboard.render.com
2. **Select your NIJA web service**
3. **Go to "Environment" tab**
4. **Click "Add Environment Variable" for each credential**:
   - Key: `KRAKEN_MASTER_API_KEY`
   - Value: [paste your master API key]
   - Click "Save"
5. **Repeat for all 6 variables** (see list above)
6. **Manually redeploy** after adding all variables

### Heroku

1. **Open your Heroku app**: https://dashboard.heroku.com
2. **Go to "Settings" tab**
3. **Click "Reveal Config Vars"**
4. **Add each variable**:
   - KEY: `KRAKEN_MASTER_API_KEY`
   - VALUE: [paste your master API key]
   - Click "Add"
5. **Repeat for all 6 variables** (see list above)
6. **Heroku will automatically restart** your dyno

### Local Development (.env file)

1. **Open or create `.env` file** in the project root
2. **Add all credentials**:

```bash
# Kraken Master Account (NIJA System)
KRAKEN_MASTER_API_KEY=your-master-api-key-here
KRAKEN_MASTER_API_SECRET=your-master-private-key-here

# Kraken User #1 (Daivon Frazier)
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-private-key-here

# Kraken User #2 (Tania Gilbert)
KRAKEN_USER_TANIA_API_KEY=tania-api-key-here
KRAKEN_USER_TANIA_API_SECRET=tania-private-key-here
```

3. **Save the file**
4. **Restart the bot**: `python3 main.py` or `bash start.sh`

⚠️ **NEVER commit the `.env` file to git!** It's already in `.gitignore`.

## Step 4: Verify Setup

After adding all credentials and restarting:

1. **Run the verification script again**:
   ```bash
   python3 verify_kraken_users.py
   ```

2. **Check the bot logs** for confirmation:
   ```
   ✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
   ✅ USER: Tania Gilbert: TRADING (Broker: Kraken)
   ```

3. **Check Kraken connection status**:
   ```bash
   python3 check_kraken_status.py
   ```

## Troubleshooting

### Issue: "SET but EMPTY (whitespace only)"

**Cause**: The environment variable contains only spaces or newlines.

**Fix**: 
1. Go to your deployment platform
2. Delete the variable
3. Re-add it, ensuring there are no extra spaces before or after the value
4. Redeploy

### Issue: "Permission denied" error

**Cause**: The API key doesn't have the required permissions.

**Fix**:
1. Go to https://www.kraken.com/u/security/api
2. Edit your API key
3. Enable all required permissions (see Step 2 above)
4. Save and restart the bot

### Issue: "Invalid nonce" error

**Cause**: Multiple bots or API clients using the same API key simultaneously.

**Fix**:
1. Create separate API keys for each bot/service
2. Never reuse API keys across multiple deployments
3. Wait 5 minutes after deleting old keys before creating new ones

### Issue: Still showing "NOT TRADING"

**Possible causes**:
1. Wrong environment variable names (check spelling, case-sensitive)
2. Credentials not saved properly on deployment platform
3. Bot not restarted after adding credentials
4. API key permissions insufficient

**Diagnosis**:
```bash
# Run verification script
python3 verify_kraken_users.py

# Check deployment logs
railway logs  # or render logs, heroku logs
```

## Alternative: Use Legacy Credentials (Master Account Only)

If you only want to enable the master account (not individual users), you can use legacy credentials:

```bash
# Instead of KRAKEN_MASTER_API_KEY/SECRET, use:
KRAKEN_API_KEY=your-api-key-here
KRAKEN_API_SECRET=your-api-secret-here
```

This is backward compatible but **does not enable user accounts**.

## Security Best Practices

1. ✅ **Never share API keys** - each account should have unique credentials
2. ✅ **Use IP whitelisting** on Kraken if deploying from fixed IP
3. ✅ **Regularly rotate API keys** (monthly recommended)
4. ✅ **Monitor API key usage** on Kraken dashboard
5. ✅ **Revoke unused keys** immediately
6. ✅ **Never commit credentials to git** - use environment variables only

## Summary

**Required Steps**:
1. ✅ Create 3 Kraken API keys (master + Daivon + Tania)
2. ✅ Add 6 environment variables to deployment platform
3. ✅ Restart/redeploy the bot
4. ✅ Verify with `python3 verify_kraken_users.py`
5. ✅ Check logs for "TRADING" status

**Expected Result**:
```
✅ MASTER: Kraken connected
✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
✅ USER: Tania Gilbert: TRADING (Broker: Kraken)
```

## Additional Resources

- **Kraken API Documentation**: https://docs.kraken.com/rest/
- **NIJA Environment Variables Guide**: `ENVIRONMENT_VARIABLES_GUIDE.md`
- **NIJA Multi-User Setup Guide**: `MULTI_USER_SETUP_GUIDE.md`
- **Kraken Permission Error Fix**: `KRAKEN_PERMISSION_ERROR_FIX.md`

## Need Help?

If issues persist after following this guide:

1. Run `python3 verify_kraken_users.py` and save the output
2. Check deployment platform logs for error messages
3. Verify API key permissions on Kraken website
4. Ensure environment variables are exactly as shown (no extra spaces)
5. Try creating fresh API keys if existing ones don't work
