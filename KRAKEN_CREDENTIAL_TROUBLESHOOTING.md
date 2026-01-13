# Kraken Credential Troubleshooting Guide

## The "Unseen Variables" Problem

### What Is This Issue?

You may encounter a situation where:
- ✅ You've set Kraken environment variables in Railway/Render
- ✅ The deployment dashboard shows the variables as "set"
- ❌ NIJA bot reports "credentials not configured"
- ❌ Diagnostic scripts show "NOT SET"

This happens when environment variables are **technically set but contain only whitespace or invisible characters**.

### Why Does This Happen?

Common causes:

1. **Copy-paste artifacts**: When copying API keys from text editors, invisible characters (newlines, tabs) get included
2. **Accidental whitespace**: Extra spaces before/after the value when pasting
3. **Text editor line endings**: Different line ending characters (CRLF vs LF)
4. **Formatted document remnants**: Copying from PDFs or formatted documents
5. **Terminal/shell escaping issues**: Quotes or escaping problems when setting values

### How to Detect This

#### Run the Enhanced Diagnostic Script

```bash
python3 diagnose_kraken_connection.py
```

**If you have malformed credentials, you'll see:**

```
⚠️  KRAKEN_MASTER_API_KEY: SET BUT INVALID (contains only whitespace/invisible characters)
⚠️  KRAKEN_MASTER_API_SECRET: SET BUT INVALID (contains only whitespace/invisible characters)

⚠️  RESULT: Master account credentials are SET but INVALID
   The environment variables contain only whitespace or invisible characters
```

#### Check Bot Logs

When NIJA starts with malformed credentials, you'll see:

```
⚠️  Kraken credentials DETECTED but INVALID for MASTER
   KRAKEN_MASTER_API_KEY: SET but contains only whitespace/invisible characters
   KRAKEN_MASTER_API_SECRET: valid
   🔧 FIX: Check your deployment platform (Railway/Render) environment variables:
      1. Remove any leading/trailing spaces or newlines from the values
      2. Ensure the values are not just whitespace characters
      3. Re-deploy after fixing the values
```

## How to Fix

### Step 1: Verify Your Actual Credentials

1. Go to https://www.kraken.com/u/security/api
2. Create a **new** API key (don't reuse old ones)
3. Required permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. **Immediately** copy the API Key and Secret to a plain text file (like Notepad, NOT Word)

### Step 2: Clean Your Credentials

Before setting them in Railway/Render:

1. **Trim whitespace**: Make sure there are no spaces before or after
2. **Check for line breaks**: Ensure the entire key is on one line
3. **No quotes**: Don't wrap the value in quotes (unless your API key literally has quotes)
4. **Plain text only**: No special formatting, just the raw API key string

### Step 3: Set in Deployment Platform

#### Railway

1. Go to your NIJA project: https://railway.app/
2. Click your service → **Variables** tab
3. **Delete** existing `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET` if present
4. Click **"+ New Variable"**
5. Key: `KRAKEN_MASTER_API_KEY`
   - Value: **Paste your cleaned API key** (Ctrl+V / Cmd+V)
   - ⚠️ **After pasting**, click in the value field and press:
     - `Home` key (go to start)
     - Hold `Shift` + `End` key (select all)
     - `Ctrl+C` / `Cmd+C` (copy)
     - `Delete` (clear field)
     - `Ctrl+V` / `Cmd+V` (paste clean)
   - This removes any invisible characters from paste
6. Repeat for `KRAKEN_MASTER_API_SECRET`
7. Click **"Deploy"** or wait for auto-deploy

#### Render

1. Go to your NIJA service: https://dashboard.render.com/
2. Click **"Environment"** tab
3. **Delete** existing `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET` if present
4. Click **"Add Environment Variable"**
5. Key: `KRAKEN_MASTER_API_KEY`
   - Value: **Paste your cleaned API key**
   - ⚠️ Use the same "re-paste" technique as Railway (above)
6. Repeat for `KRAKEN_MASTER_API_SECRET`
7. Click **"Save Changes"**
8. Click **"Manual Deploy"** → **"Deploy latest commit"**

### Step 4: Verify the Fix

After redeployment, check the logs. You should see:

```
✅ KRAKEN (Master): Configured (Key: 16 chars, Secret: 88 chars)
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
```

Or run the diagnostic:

```bash
python3 diagnose_kraken_connection.py
```

Expected output:

```
✅ KRAKEN_MASTER_API_KEY: SET (Krak...xyz)
✅ KRAKEN_MASTER_API_SECRET: SET (vXy2...abc)

✅ RESULT: Master account is configured for Kraken
```

## Advanced: Local Testing

If deploying to Railway/Render, you can test locally first:

### Create .env file

```bash
# Create .env in repository root
cat > .env << 'EOF'
# Kraken Master Account
KRAKEN_MASTER_API_KEY=your-actual-api-key-here
KRAKEN_MASTER_API_SECRET=your-actual-api-secret-here
EOF
```

### Run diagnostic

```bash
python3 diagnose_kraken_connection.py
```

### Test connection

```bash
python3 << 'EOF'
import os
from dotenv import load_dotenv
load_dotenv()

import sys
sys.path.insert(0, 'bot')
from broker_manager import KrakenBroker, AccountType
import logging

logging.basicConfig(level=logging.INFO)

broker = KrakenBroker(account_type=AccountType.MASTER)
result = broker.connect()
print(f"\nConnection successful: {result}")
EOF
```

### Clean up

```bash
# IMPORTANT: Never commit .env
rm .env
git status  # verify .env is not staged
```

## Prevention Tips

### When Creating API Keys

1. Copy directly from Kraken website to a plain text editor (Notepad, TextEdit, nano)
2. Don't copy from PDFs, screenshots, or formatted documents
3. Verify the key visually - should be a long alphanumeric string
4. No line breaks within the key itself

### When Setting Environment Variables

1. Always use the deployment platform's web interface (not command line)
2. Paste values directly (don't type them manually)
3. Use the "re-paste" technique to clean invisible characters
4. Double-check: no extra spaces before/after the value
5. Test immediately after setting

### Best Practices

1. **Use a password manager**: Store API keys in 1Password, LastPass, or Bitwarden
2. **Keep backups**: Save keys in a secure, encrypted location
3. **Rotate regularly**: Generate new API keys every 90 days
4. **Test before production**: Verify connection works before live trading
5. **Monitor logs**: Watch startup logs for credential warnings

## Still Having Issues?

### Common Questions

**Q: I set the variables but they still show as NOT SET**  
**A:** Redeploy after setting variables. Railway auto-redeploys, but Render requires manual deploy.

**Q: The diagnostic shows "SET" but connection still fails**  
**A:** This means credentials are valid format but wrong values or permissions. Check:
- API key has trading permissions enabled
- You copied the full key (very long string)
- You're using the right account (master vs user)

**Q: Connection works locally but not on Railway/Render**  
**A:** Environment variables in `.env` file only work locally. You must set them in Railway/Render dashboard.

**Q: I keep getting "Invalid nonce" errors**  
**A:** This is different from credential issues. NIJA has advanced nonce handling built-in. If you see this:
- Check system clock is synchronized
- Restart the bot
- See `KRAKEN_NONCE_IMPROVEMENTS.md` for details

### Get More Help

1. **Check existing docs**: 
   - `KRAKEN_SETUP_GUIDE.md` - Full setup instructions
   - `KRAKEN_ENV_VARS_REFERENCE.md` - Environment variable reference
   - `KRAKEN_DEPLOYMENT_ANSWER.md` - Deployment-specific guidance

2. **Run diagnostic tools**:
   ```bash
   python3 diagnose_kraken_connection.py  # Kraken-specific
   python3 diagnose_env_vars.py           # All environment variables
   python3 check_kraken_status.py         # Quick status check
   ```

3. **Enable debug logging**: Set `LOG_LEVEL=DEBUG` in environment variables

4. **Check Railway/Render logs**: Look for the exact error message when bot starts

## Summary Checklist

Before asking for help, verify:

- [ ] API key and secret copied from Kraken website (not from old notes)
- [ ] No extra spaces/newlines before or after the values
- [ ] Values set in Railway/Render dashboard (not just .env file)
- [ ] Redeployed after setting the values
- [ ] Diagnostic shows "SET" (not "NOT SET" or "SET BUT INVALID")
- [ ] API key has correct permissions on Kraken website
- [ ] Checked recent deployment logs for detailed error messages

If all items are checked and it still doesn't work, there may be a platform-specific issue. Check Railway/Render status pages and support.

---

**Last Updated**: January 13, 2026  
**NIJA Version**: APEX V7.2  
**Related Docs**: `KRAKEN_SETUP_GUIDE.md`, `ANSWER_WHY_KRAKEN_NOT_CONNECTING.md`
