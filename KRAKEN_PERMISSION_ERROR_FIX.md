# Fixing Kraken API Permission Errors

## Error Message
If you see this error when starting the bot:

```
❌ Kraken connection test failed: EGeneral:Permission denied

   ⚠️  API KEY PERMISSION ERROR
   Your Kraken API key does not have the required permissions.
```

This means your Kraken API key doesn't have the correct permissions enabled.

## Why This Happens
Kraken API keys can be created with limited permissions for security. By default, new API keys may not have all the permissions needed for automated trading.

## How to Fix

### Step 1: Go to Kraken API Management
1. Log in to your Kraken account
2. Go to: https://www.kraken.com/u/security/api
3. Find the API key you're using with NIJA bot
   - If you're not sure which one, check your environment variables:
     - `KRAKEN_MASTER_API_KEY` for master account
     - `KRAKEN_USER_{NAME}_API_KEY` for user accounts

### Step 2: Edit API Key Permissions
1. Click "Edit" or the settings icon next to your API key
2. Enable the following permissions:

   **Required Permissions:**
   - ✅ **Query Funds** - Allows the bot to check your account balance
   - ✅ **Query Open Orders & Trades** - Allows the bot to track active positions
   - ✅ **Query Closed Orders & Trades** - Allows the bot to review trade history
   - ✅ **Create & Modify Orders** - Allows the bot to place trades
   - ✅ **Cancel/Close Orders** - Allows the bot to place stop losses and exit positions

   **DO NOT Enable:**
   - ❌ **Withdraw Funds** - For security, the bot does not need withdrawal permissions

### Step 3: Save and Restart
1. Click "Save" or "Update" to save the permission changes
2. **Important**: Changes may take a few minutes to propagate
3. Restart your NIJA bot
   - On Railway/Render: Trigger a new deployment
   - On local machine: Stop and restart the bot

### Step 4: Verify Fix
After restarting, you should see:
```
✅ KRAKEN PRO CONNECTED (MASTER)
   or
✅ KRAKEN PRO CONNECTED (USER:your_username)
```

Instead of the permission error.

## Troubleshooting

### Still Getting Permission Errors?
1. **Double-check all required permissions are enabled**
   - Query Funds
   - Query Open Orders & Trades
   - Query Closed Orders & Trades
   - Create & Modify Orders
   - Cancel/Close Orders

2. **Wait a few minutes after saving**
   - Kraken's API permission changes may take 1-5 minutes to take effect

3. **Verify you're editing the correct API key**
   - Make sure the API key in your environment variables matches the one you edited

4. **Check for typos in environment variables**
   - API keys are case-sensitive
   - No extra spaces before/after the key
   - No missing characters

### Getting "Invalid Nonce" Errors?
If you see "EAPI:Invalid nonce" errors after a permission error:
- This is a side effect of retry attempts after permission failures
- The fix in this PR prevents these nonce errors
- Update to the latest version which includes the permission retry prevention fix

### Still Having Issues?
1. **Regenerate your API key**:
   - Go to Kraken API management
   - Delete the old API key
   - Create a new one with all required permissions
   - Update your environment variables with the new credentials
   - Restart the bot

2. **Check Kraken account status**:
   - Make sure your Kraken account is fully verified
   - Some API features require higher verification levels

3. **Contact Support**:
   - If all else fails, contact Kraken support to verify your API key permissions
   - Mention you need permissions for automated trading via REST API

## Security Best Practices

### ✅ DO:
- Use separate API keys for each bot/application
- Regularly rotate (regenerate) your API keys
- Only enable permissions your bot actually needs
- Store API keys securely in environment variables
- Never commit API keys to version control

### ❌ DON'T:
- Share your API keys with anyone
- Enable "Withdraw Funds" permission unless absolutely necessary
- Use the same API key across multiple bots/apps
- Store API keys in plain text files
- Post API keys in support channels or screenshots

## For User Accounts

If you're setting up a user account (not the master account), your environment variable names will be different:

```bash
# Master account
KRAKEN_MASTER_API_KEY=your-key-here
KRAKEN_MASTER_API_SECRET=your-secret-here

# User accounts (replace TANIA with user's first name in uppercase)
KRAKEN_USER_TANIA_API_KEY=tania-key-here
KRAKEN_USER_TANIA_API_SECRET=tania-secret-here

KRAKEN_USER_DAIVON_API_KEY=daivon-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-secret-here
```

See `MULTI_USER_SETUP_GUIDE.md` for complete user account setup instructions.

## Additional Resources

- **Kraken API Documentation**: https://docs.kraken.com/rest/
- **Kraken API Key Management**: https://www.kraken.com/u/security/api
- **NIJA Multi-User Setup**: See `MULTI_USER_SETUP_GUIDE.md`
- **Environment Variables Guide**: See `KRAKEN_ENV_VARS_REFERENCE.md`
