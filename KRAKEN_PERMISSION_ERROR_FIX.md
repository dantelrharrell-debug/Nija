# Fix Kraken "Permission Denied" Error

**Last Updated**: January 10, 2026

---

## ❌ The Error

If you see this in your logs:

```
2026-01-10 11:47:26 | ERROR | ❌ Kraken connection test failed (USER:daivon_frazier): EGeneral:Permission denied
```

Or:

```
❌ Kraken connection test failed: Permission denied
```

**This means:** Your Kraken API key is valid (it connects to Kraken), but it doesn't have the required permissions to query account information or place trades.

---

## ✅ The Solution

### Step 1: Log into Kraken

Go to: https://www.kraken.com/u/security/api

### Step 2: Find Your API Key

Look for the API key you're using with NIJA. You can identify it by:
- The key name/description you gave it
- The last few characters of the key
- The creation date

### Step 3: Edit API Key Permissions

Click "Edit" or "Manage" next to your API key.

### Step 4: Enable Required Permissions

**Enable these permissions** (check the boxes):

- ✅ **Query Funds** - *Required to check account balance*
- ✅ **Query Open Orders & Trades** - *Required for position tracking*
- ✅ **Query Closed Orders & Trades** - *Required for trade history*
- ✅ **Create & Modify Orders** - *Required to place trades*
- ✅ **Cancel/Close Orders** - *Required for stop losses*

**For security, DO NOT enable:**

- ❌ **Withdraw Funds** - Not needed for trading, only for withdrawals

### Step 5: Save Changes

Click "Save" or "Update API Key"

### Step 6: Restart the Bot

- **Local**: Stop the bot (Ctrl+C) and start it again
- **Railway**: The bot will auto-restart after a few seconds
- **Render**: Click "Manual Deploy" to restart
- **Heroku**: `heroku restart`

---

## Why This Happens

### Common Causes

1. **API Key Created with "View Only" Permissions**
   - When creating an API key on Kraken, you must explicitly enable trading permissions
   - The default or "minimal" permissions only allow viewing, not trading

2. **Permissions Were Changed**
   - Someone edited the API key and removed permissions
   - API key was regenerated with different permissions

3. **Using Wrong API Key**
   - You have multiple API keys, and the one in your `.env` file has limited permissions
   - Check which key you're actually using

---

## Verify the Fix

After enabling permissions and restarting, check your logs for:

### ✅ Success

```
📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ KRAKEN PRO CONNECTED (USER:daivon_frazier)
   Account: USER:daivon_frazier
   USD Balance: $XXX.XX
   USDT Balance: $XXX.XX
   Total: $XXX.XX
```

### ❌ Still Failing

If you still see "Permission denied":

1. **Double-check permissions** - Make sure ALL 5 required permissions are enabled
2. **Wait a moment** - Sometimes Kraken takes 30-60 seconds to propagate permission changes
3. **Try regenerating the API key**:
   - Delete the old key
   - Create a new key with all required permissions
   - Update your `.env` file or deployment environment variables
   - Restart the bot

---

## For Deployment Platforms

After fixing permissions in Kraken, you may also need to update environment variables:

### Railway

1. Go to Railway dashboard
2. Select your NIJA project
3. Click "Variables"
4. Verify these are set:
   - `KRAKEN_USER_DAIVON_API_KEY` (for User #1)
   - `KRAKEN_USER_DAIVON_API_SECRET`
5. If you regenerated the key, update the values
6. Railway will auto-redeploy

### Render

1. Go to Render dashboard
2. Select your NIJA service
3. Go to "Environment" tab
4. Verify variables are set (same as Railway)
5. Click "Manual Deploy" to restart

---

## Security Note

**Never enable "Withdraw Funds" permission** unless you absolutely need it for a specific use case.

This permission allows the API key to withdraw funds from your Kraken account. NIJA does not need this permission for trading.

If an attacker gains access to your API key, they could drain your account if withdrawal permissions are enabled.

---

## Quick Reference: Required Permissions

```
✅ Query Funds
✅ Query Open Orders & Trades
✅ Query Closed Orders & Trades
✅ Create & Modify Orders
✅ Cancel/Close Orders
❌ Withdraw Funds (DO NOT enable)
```

---

## Related Documentation

- **Environment Variables Guide**: `ENVIRONMENT_VARIABLES_GUIDE.md`
- **Kraken Setup Guide**: `KRAKEN_CONNECTION_STATUS.md`
- **Multi-Account Guide**: `MASTER_USER_ACCOUNT_SEPARATION_GUIDE.md`

---

## Still Having Issues?

If you've followed all these steps and still see "Permission denied":

1. Check the exact error message in logs - it might be a different issue
2. Verify you're editing the correct API key (the one referenced in your env vars)
3. Try creating a completely new API key with all permissions
4. Contact Kraken support if the issue persists

---

**Summary**: The "Permission denied" error means your API key needs more permissions. Enable all 5 required permissions in your Kraken API settings, save, and restart the bot.
