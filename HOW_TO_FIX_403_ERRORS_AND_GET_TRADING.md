# How to Handle 403 "Too many errors" and Get Trading Again

## Quick Fix Guide

### Step 1: Stop Restarting the Bot

**⚠️ CRITICAL**: If you're seeing 403 errors, **DO NOT** keep restarting the bot!

Each restart makes the problem worse by:
- Making more failed API calls
- Extending the Coinbase API key block
- Resetting the retry counter

### Step 2: Let the Retry Logic Work

The bot is **already doing the right thing**:

```
Current: Attempt 5/10, waiting 120 seconds
Next:    Attempt 6/10, waiting 120 seconds
...up to: Attempt 10/10
```

**Total maximum wait**: ~13-14 minutes from first attempt

### Step 3: If All Retries Fail

If you see this message:
```
❌ Failed to connect after maximum retry attempts
```

**Do this**:

1. **Wait 30-60 minutes** before doing ANYTHING
   - This allows Coinbase's API key block to fully expire
   - Shorter waits may not be enough

2. **Check your API credentials** are valid:
   ```bash
   # On Railway or deployment platform
   # Verify these environment variables are set:
   echo $COINBASE_API_KEY
   echo $COINBASE_API_SECRET
   ```

3. **Verify API key permissions** in Coinbase:
   - Log into Coinbase
   - Go to Settings → API Keys
   - Check your key is:
     - ✅ Not expired
     - ✅ Not revoked
     - ✅ Has "Trading" permission enabled
     - ✅ Has "View" permission enabled

4. **Check Coinbase account status**:
   - Account in good standing
   - No security holds
   - No pending verification
   - Sufficient balance

5. **After waiting 30-60 minutes**, restart the bot **ONCE**:
   ```bash
   # On Railway: trigger a redeploy
   # Or locally:
   python bot.py
   ```

### Step 4: Monitor the New Attempt

Watch for success message:
```
✅ Connected to Coinbase Advanced Trade API
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE
```

If you see 403 errors again:
- **Wait even longer** (2-4 hours)
- **Check for Coinbase service issues**: https://status.coinbase.com/
- **Consider that API credentials might be invalid**

---

## Understanding the 403 Error

### What It Means

**403 "Too many errors"** = Coinbase temporarily blocked your API key

This is **NOT** the same as:
- **429 "Too many requests"** (rate limiting)
- **401 "Unauthorized"** (bad credentials)
- **500 "Server error"** (Coinbase issue)

### Why It Happens

Common causes:
1. **Rapid bot restarts** (most common)
   - Each restart makes API calls
   - Multiple restarts = many calls in short time
   - Triggers Coinbase's abuse detection

2. **Previous errors**
   - If bot had errors in previous runs
   - Failed API calls count against your limit
   - Eventually triggers temporary block

3. **Invalid credentials being retried**
   - If credentials are wrong
   - Repeated failed auth attempts
   - Coinbase blocks the key to prevent brute force

4. **Network issues**
   - Timeouts and connection errors
   - Get counted as errors by Coinbase
   - Multiple timeouts trigger block

### How Long It Lasts

Typical duration:
- **Minimum**: 5 minutes
- **Common**: 15-30 minutes
- **Worst case**: 1-2 hours

Depends on:
- How many errors triggered it
- How recently errors occurred
- Your API key's "reputation"

---

## Prevention: Avoid Future 403 Blocks

### ✅ Do This

1. **Don't restart rapidly**
   - Wait at least 5-10 minutes between restarts
   - Let retry logic work instead of restarting

2. **Fix errors promptly**
   - Monitor logs for errors
   - Address root causes
   - Don't let errors pile up

3. **Use proper error handling**
   - The bot already has this
   - Exponential backoff is built in
   - Trust the retry logic

4. **Monitor API health**
   - Check https://status.coinbase.com/
   - Don't deploy during outages
   - Wait for "All Systems Operational"

5. **Keep credentials valid**
   - Rotate API keys carefully
   - Update environment variables properly
   - Test new keys before deploying

### ❌ Avoid This

1. **Rapid restarts** (< 5 minutes apart)
2. **Ignoring errors** (fix them instead)
3. **Testing in production** (use testnet)
4. **Deploying during outages**
5. **Using invalid credentials**

---

## Advanced: Verify Connection Without Starting Bot

Use this script to test if the API block has cleared:

```python
#!/usr/bin/env python3
"""Test Coinbase connection without starting full bot"""

import os
from coinbase.rest import RESTClient

try:
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ API credentials not found in environment")
        exit(1)
    
    print("🔍 Testing Coinbase connection...")
    client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    accounts = client.get_accounts()
    print("✅ Connection successful!")
    print(f"   Found {len(accounts.accounts)} accounts")
    
except Exception as e:
    if "403" in str(e) or "forbidden" in str(e).lower():
        print("❌ Still blocked (403 error)")
        print("   Wait longer before retrying")
    elif "401" in str(e):
        print("❌ Invalid credentials (401 error)")
        print("   Check API key and secret")
    else:
        print(f"❌ Connection failed: {e}")
```

Save as `test_connection_simple.py` and run:
```bash
python test_connection_simple.py
```

---

## Current Retry Settings (In Code)

The bot uses these settings (already optimized):

```python
max_attempts = 10          # Maximum retry attempts
base_delay = 15.0          # Starting delay (seconds)
max_delay = 120.0          # Maximum delay cap
startup_delay = 45         # Initial wait before first attempt
```

**Retry schedule**:
| Attempt | Delay | Cumulative |
|---------|-------|------------|
| 1 | 0s | 45s (startup) |
| 2 | 15s | 60s |
| 3 | 30s | 90s |
| 4 | 60s | 150s (~2.5 min) |
| 5 | 120s | 270s (~4.5 min) |
| 6 | 120s | 390s (~6.5 min) |
| 7 | 120s | 510s (~8.5 min) |
| 8 | 120s | 630s (~10.5 min) |
| 9 | 120s | 750s (~12.5 min) |
| 10 | 120s | 870s (~14.5 min) |

**Total time**: Up to ~14.5 minutes before giving up

This is **already optimal** for 403 errors. Don't change it.

---

## What to Tell Users

If users ask "Is the bot trading?":

**If seeing 403 errors**:
```
⚠️  Bot is trying to connect but Coinbase temporarily blocked the API key.

The bot will automatically retry for up to 15 minutes.

If you just restarted the bot, this is expected. 
Please wait 15 minutes and check again.

Don't restart the bot - this makes it worse.
```

**If all retries failed**:
```
❌ Bot couldn't connect after 10 attempts.

This means Coinbase has a longer API key block in place.

Action needed:
1. Wait 30-60 minutes
2. Verify API credentials are valid
3. Restart the bot ONCE
4. Check https://status.coinbase.com/ for outages

Do NOT restart multiple times.
```

---

## Related Documentation

- `FIX_403_FORBIDDEN_ERROR.md` - Technical details on the 403 fix
- `BROKER_CONNECTION_FIX_JAN_2026.md` - General connection troubleshooting
- `RATE_LIMITING_FIX_JAN_2026.md` - Rate limiting (429 errors)
- `ANSWER_IS_NIJA_TRADING_FOR_USER1_NOW_JAN9_2026.md` - Current status answer

---

## Summary

### The Problem
Bot gets 403 "Too many errors" from Coinbase when:
- Restarted too frequently
- Previous runs had errors
- API key hit error limits

### The Solution
1. ✅ **Stop restarting** the bot
2. ✅ **Wait for retry logic** to work (~15 minutes)
3. ✅ **If it fails, wait 30-60 minutes** before next attempt
4. ✅ **Verify credentials** are valid
5. ✅ **Check Coinbase status** for outages

### The Prevention
1. ✅ Don't restart rapidly (wait 5-10 minutes between)
2. ✅ Fix errors promptly
3. ✅ Keep credentials valid
4. ✅ Monitor for issues
5. ✅ Trust the retry logic

---

**Author**: GitHub Copilot  
**Date**: January 9, 2026  
**Status**: Ready for use
