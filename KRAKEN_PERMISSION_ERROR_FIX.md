# Fixing Kraken API Permission Errors

## Error Message
If you see this error when starting the bot:

```
❌ Kraken connection test failed: EGeneral:Permission denied

   ⚠️  API KEY PERMISSION ERROR
   Your Kraken API key does not have the required permissions.
```

This means your Kraken API key doesn't have the correct permissions enabled or the wrong key type is being used.

## Complete Fix Checklist

### 🔧 FIX #1 — Add Kraken MASTER keys to your environment

Make sure you're using the correct environment variable names:

**For Master Account:**
```bash
KRAKEN_MASTER_API_KEY=your-master-api-key-here
KRAKEN_MASTER_API_SECRET=your-master-private-key-here
```

**NOT the legacy format:**
```bash
# ❌ Don't use these (legacy)
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
```

**For User Accounts:**
```bash
# User accounts use first name in uppercase
KRAKEN_USER_DAIVON_API_KEY=daivon-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-secret-here

KRAKEN_USER_TANIA_API_KEY=tania-key-here
KRAKEN_USER_TANIA_API_SECRET=tania-secret-here
```

### 🔧 FIX #2 — Fix USER Kraken API permissions (this is mandatory)

Each Kraken API key MUST have the following permissions enabled:

1. **Go to Kraken API Management:**
   - Log in to: https://www.kraken.com/u/security/api
   - Find the API key you're using with NIJA bot

2. **Edit API Key Permissions:**
   Click "Edit" and enable these permissions:

   **Required Permissions (all mandatory):**
   - ✅ **Query Funds** - Allows the bot to check your account balance
   - ✅ **Query Open Orders & Trades** - Allows the bot to track active positions
   - ✅ **Query Closed Orders & Trades** - Allows the bot to review trade history
   - ✅ **Create & Modify Orders** - Allows the bot to place trades
   - ✅ **Cancel/Close Orders** - Allows the bot to place stop losses and exit positions

   **DO NOT Enable (security risk):**
   - ❌ **Withdraw Funds** - The bot does NOT need withdrawal permissions

3. **Save and Wait:**
   - Click "Save" to save the permission changes
   - Wait 1-5 minutes for changes to propagate
   - Restart your NIJA bot

### 🔧 FIX #3 — Confirm Kraken key type

**CRITICAL:** You must use a **Classic API key**, NOT OAuth or App keys.

**To verify your key type:**
1. Go to: https://www.kraken.com/u/security/api
2. Look at your API key - it should show "Classic API Key"
3. If it says "OAuth" or "App Key", you need to create a new Classic API key

**To create a Classic API key:**
1. Go to: https://www.kraken.com/u/security/api
2. Click **"Generate New Key"** (NOT "Create OAuth Application")
3. Set a descriptive name (e.g., "NIJA Trading Bot - Master")
4. Enable all required permissions (see FIX #2 above)
5. Click "Generate Key"
6. Copy both the **API Key** and **Private Key** immediately
   - You won't be able to see the Private Key again!
7. Update your environment variables with the new credentials

**Key Types Explained:**
- ✅ **Classic API Key**: Direct REST API access (what NIJA needs)
- ❌ **OAuth Key**: For third-party applications (not compatible)
- ❌ **App Key**: For mobile/web apps (not compatible)

### 🔧 FIX #4 — Confirm Kraken nonce handling (if still failing)

**Good news:** The bot automatically handles nonce correctly! It uses:
- ✅ **Microsecond precision** (better than milliseconds)
- ✅ **Monotonically increasing** nonces (guaranteed to never decrease)
- ✅ **10-20 second forward offset** to prevent restart conflicts
- ✅ **Thread-safe generation** to prevent race conditions

**If you still see nonce errors after fixes #1-3:**

1. **Check system clock synchronization:**
   ```bash
   # On Linux/Mac
   sudo ntpdate -s time.nist.gov
   
   # Or use systemd-timesyncd
   sudo timedatectl set-ntp true
   ```

2. **Verify no other applications are using the same API key:**
   - Each application/bot must have its own API key
   - Using the same key in multiple places causes nonce conflicts

3. **Check for clock drift:**
   - Ensure your server's clock is accurate
   - Enable NTP (Network Time Protocol) synchronization
   - For cloud servers, this is usually automatic

## Why This Happens
Kraken API keys can be created with limited permissions for security. Additionally, there are different types of API keys, and only Classic API keys work with trading bots.

**Common Causes:**
1. **Wrong key type**: Using OAuth or App key instead of Classic API key
2. **Missing permissions**: API key doesn't have Query/Create/Cancel permissions
3. **Wrong environment variables**: Using legacy KRAKEN_API_KEY instead of KRAKEN_MASTER_API_KEY
4. **Nonce issues**: System clock drift or duplicate API key usage

## How to Fix

Follow all four fixes in order:

### Step 1: Verify Environment Variables (FIX #1)

Make sure you're using the correct environment variable names based on your deployment:

#### Local Development (.env file)
```bash
# Master account - CORRECT format
KRAKEN_MASTER_API_KEY=your-master-api-key-here
KRAKEN_MASTER_API_SECRET=your-master-private-key-here

# User accounts - CORRECT format  
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-private-key-here
```

#### Production (Railway/Render)
Add these exact variable names in your deployment platform's environment variables section.

### Step 2: Fix API Permissions (FIX #2)

This is **mandatory** - all permissions must be enabled:
1. Log in to your Kraken account
2. Go to: https://www.kraken.com/u/security/api
3. Find the API key you're using with NIJA bot
   - If you're not sure which one, check your environment variables:
     - `KRAKEN_MASTER_API_KEY` for master account
     - `KRAKEN_USER_{NAME}_API_KEY` for user accounts
4. Click "Edit" or the settings icon next to your API key

### Step 3: Confirm Classic API Key Type (FIX #3)

**Before editing permissions**, verify you have a Classic API key:

1. **Check the key type** on the API management page
   - It should say **"Classic API Key"** or just "API Key"
   - If it says "OAuth" or "App Key", you have the WRONG type

2. **If wrong type, create a new Classic API key:**
   - Click **"Generate New Key"** (NOT "Create OAuth Application")
   - Set a descriptive name: "NIJA Trading Bot - Master" or "NIJA Trading Bot - [Username]"
   - Continue to Step 4 to set permissions
   - After creating, update your environment variables with the new credentials

3. **If correct type (Classic)**, proceed to Step 4 to verify permissions

### Step 4: Enable Required Permissions (FIX #2 continued)
1. In the API key edit screen, enable the following permissions:

   **Required Permissions (ALL must be checked):**
   - ✅ **Query Funds** - Allows the bot to check your account balance
   - ✅ **Query Open Orders & Trades** - Allows the bot to track active positions
   - ✅ **Query Closed Orders & Trades** - Allows the bot to review trade history
   - ✅ **Create & Modify Orders** - Allows the bot to place trades
   - ✅ **Cancel/Close Orders** - Allows the bot to place stop losses and exit positions

   **DO NOT Enable:**
   - ❌ **Withdraw Funds** - For security, the bot does NOT need withdrawal permissions

2. Click "Save" or "Update" to save the permission changes

### Step 5: Verify Nonce Handling (FIX #4)

The bot automatically handles nonce correctly, but verify these items:

1. **System Clock Sync (for VPS/cloud servers):**
   ```bash
   # Check if NTP is enabled
   timedatectl status | grep "NTP synchronized"
   
   # If not synchronized, enable it
   sudo timedatectl set-ntp true
   ```

2. **No Duplicate API Key Usage:**
   - Each bot instance must have its own unique API key
   - Don't use the same API key in multiple applications/bots
   - Don't share API keys between master and user accounts

3. **Bot Nonce Status:**
   - The bot uses **microsecond precision** nonces (1,000,000 nonces per second)
   - Nonces are **monotonically increasing** (never decrease)
   - Each restart uses a **10-20 second forward offset** to prevent conflicts

### Step 6: Save, Wait, and Restart
1. After making all changes, **wait 1-5 minutes** for Kraken to propagate the changes
2. Restart your NIJA bot:
   - **Railway/Render**: Trigger a new deployment or restart service
   - **Local machine**: Stop (Ctrl+C) and restart: `./start.sh`
   - **Docker**: `docker restart nija-bot`

### Step 7: Verify Fix
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
