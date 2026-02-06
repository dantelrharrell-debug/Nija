# Platform Account Configuration - Recommended for Optimal Operation

**Version:** 1.1  
**Last Updated:** February 6, 2026  
**Status:** RECOMMENDED - Optimal for production stability

---

## The ONE Fix for Cleaner Logs and Stable Startup

### Current Behavior

When running NIJA with only user accounts (no Platform account), you may see:

- ℹ️  **Informational messages** about Platform account not connected
- ℹ️  **Recommendation** to configure Platform account
- ℹ️  **Suggestions** for optimal system operation

### The Solution

**Configure Platform Kraken credentials for optimal operation.**

This configuration change will:
- ✅ **Enable Platform to trade independently** (additional trading capacity)
- ✅ **Stabilize startup flow** 
- ✅ **Provide cleaner, quieter logs**
- ✅ **Improve system initialization**

---

## Understanding the Architecture

### Independent Trading Model

NIJA uses an **independent trading model** where all accounts trade separately:

```
🔷 PLATFORM ACCOUNT (Independent Trader #1)
   ↓ Uses NIJA signals + execution logic
   ↓ Trades with its own capital
   
👤 USER ACCOUNT 1 (Independent Trader #2)
   ↓ Uses same NIJA signals + execution logic
   ↓ Trades with their own capital
   
👤 USER ACCOUNT 2 (Independent Trader #3)
   ↓ Uses same NIJA signals + execution logic
   ↓ Trades with their own capital
```

**Key Points:**
- ❌ Platform is **NOT** a "master" account
- ❌ Platform does **NOT** control user accounts
- ❌ Platform is **NOT** a capital allocator
- ✅ Platform **IS** just another independent trader
- ✅ All accounts trade **independently** using same logic
- ✅ All accounts are **equal** - no hierarchy

---

## How to Configure Platform Account

### Step 1: Get Kraken API Credentials

1. Log in to [Kraken.com](https://www.kraken.com)
2. Go to **Settings → API**
3. Click **"Generate New Key"**
4. **IMPORTANT:** Use "Classic API Key" (NOT OAuth)
5. Enable **required permissions:**
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable "Withdraw Funds"
6. Copy the **API Key** and **API Secret**

### Step 2: Set Environment Variables

#### For Local Development (`.env` file):

```bash
# Platform Kraken credentials (REQUIRED for stable operation)
KRAKEN_PLATFORM_API_KEY=your-api-key-here
KRAKEN_PLATFORM_API_SECRET=your-api-secret-here
```

#### For Railway/Render/Heroku (Platform Dashboard):

Add these environment variables:
- `KRAKEN_PLATFORM_API_KEY` = your API key
- `KRAKEN_PLATFORM_API_SECRET` = your API secret

#### For Railway Specifically:
1. Go to your project → **Variables** tab
2. Click **"+ New Variable"**
3. Add `KRAKEN_PLATFORM_API_KEY` with your API key
4. Add `KRAKEN_PLATFORM_API_SECRET` with your API secret
5. Click **Deploy**

### Step 3: Verify Configuration

After setting credentials, restart the bot and check logs:

**Quick Check (Recommended):**
```bash
# Run the credential validation script
python3 check_platform_credentials.py
```

This script will:
- ✅ Check if credentials are configured
- ✅ Detect whitespace issues
- ✅ Provide actionable fix instructions
- ✅ Verify configuration is correct

**Manual Check in Logs:**

**✅ Success indicators:**
```
✅ Kraken Platform credentials detected
🔷 PLATFORM ACCOUNTS (Primary Trading Accounts):
   • KRAKEN: ✅ CONNECTED
✅ ACCOUNT HIERARCHY STATUS:
   ✅ All user accounts have corresponding Platform accounts (correct hierarchy)
```

**❌ Still seeing warnings?**
```
⚠️  Kraken Platform credentials NOT SET
⚠️  ACCOUNT PRIORITY WARNINGS:
   ⚠️  User accounts trading WITHOUT Platform account on: KRAKEN
```

If you see warnings, verify:
1. Environment variables are spelled correctly (case-sensitive)
2. No leading/trailing whitespace in credential values
3. Deployment platform has restarted after setting variables
4. API credentials are valid (check Kraken dashboard)

---

## Why Configure Platform Account?

### Benefits

**1. Platform trades independently** - Additional trading capacity
- Platform account is another independent trader
- Uses same NIJA signals and execution logic
- Deploys more capital in the strategy

**2. Cleaner system operation**
- Less verbose startup logs
- Smoother initialization flow
- Fewer informational messages

**3. All accounts are equal**
- No hierarchy or master/follower relationship
- All accounts are independent traders
- Each manages its own capital and positions

### Minimum Balance Recommendations

| Account Purpose | Minimum Balance | Notes |
|----------------|-----------------|-------|
| **Platform account** | $50+ | Trades independently like any user account |
| **User accounts** | $50+ | Each user trades independently |

**Note:** Platform account CAN have $0 balance (it just won't trade), but recommended to fund it so it trades alongside users.

### Trading Control

All accounts trade independently:
- Set `PLATFORM_ACCOUNT_TIER=BALLER` in `.env` for best risk parameters
- Platform trades independently from user accounts
- Each account has its own capital, positions, and risk limits
- All use same NIJA signal generation and execution logic

---

## Frequently Asked Questions

### Q: Is Platform account required?

**A:** No, but it's recommended. Without Platform account:
- ✅ System still works normally
- ℹ️  Informational messages suggest configuring Platform
- ✅ User accounts trade independently
- ❌ Missing Platform's trading capacity

For production use, **Platform account is required**.

### Q: Will configuring Platform account change my existing user account trading?

**A:** No. User accounts continue to trade independently. Platform account connection only affects:
- System hierarchy validation
- Startup flow stability
- Log verbosity
- Production readiness status

### Q: What if I only want one account to trade?

**A:** Configure that one account as the Platform account:
- Set `KRAKEN_PLATFORM_API_KEY` and `KRAKEN_PLATFORM_API_SECRET`
- Don't configure any user account credentials
- System will run in single-account mode with clean hierarchy

### Q: Can I have Platform account on one exchange and user accounts on another?

**A:** Yes. For example:
- Platform account on Kraken
- User accounts on Alpaca (stocks) or OKX (crypto)

Each exchange can have its own Platform account if needed.

### Q: Do I need Platform accounts for all exchanges?

**A:** You only need Platform account for exchanges where you have user accounts. For example:

**Scenario A: Only user accounts on Kraken**
- ✅ Configure `KRAKEN_PLATFORM_API_KEY/SECRET` (required)
- ❌ Don't need Alpaca Platform credentials

**Scenario B: User accounts on Kraken AND Alpaca**
- ✅ Configure `KRAKEN_PLATFORM_API_KEY/SECRET` (required)
- ✅ Configure `ALPACA_API_KEY/SECRET` (Platform account, required)

### Q: What happens if Platform account connection fails?

**A:** Check logs for specific errors:
- Invalid credentials → Verify in Kraken dashboard
- Whitespace in credentials → Re-paste without extra spaces
- Wrong permission → Enable required API permissions
- Network issues → Check Kraken API status

System will continue attempting connection and display warnings until Platform account connects successfully.

---

## Troubleshooting

### Issue: Hierarchy warnings still appear after configuring Platform credentials

**Solution:**
1. Verify environment variables are set correctly:
   ```bash
   # Local development
   cat .env | grep KRAKEN_PLATFORM
   
   # Production (Railway)
   # Check Variables tab in Railway dashboard
   ```
2. Check for whitespace in credentials:
   - Leading/trailing spaces cause authentication failures
   - Re-paste credentials carefully
3. Restart the application after setting variables
4. Check logs for connection errors
5. Verify API permissions in Kraken dashboard

### Issue: "MALFORMED" credential warnings

**Solution:**
This happens when credentials contain only whitespace:
1. In Railway/Render dashboard, delete the variable
2. Re-add with correct value (no extra spaces)
3. Click Save and redeploy

### Issue: Platform connects but still shows warnings

**Solution:**
Check if Platform account is actually connected:
```
🔷 PLATFORM ACCOUNTS (Primary Trading Accounts):
   • KRAKEN: ❌ NOT CONNECTED  ← Should be ✅ CONNECTED
```

If showing "NOT CONNECTED", check:
- API credentials are valid
- API permissions are enabled
- No IP restrictions on API key
- Kraken service is operational

---

## Related Documentation

- **[API_CREDENTIALS_GUIDE.md](API_CREDENTIALS_GUIDE.md)** - Detailed credential setup
- **[PLATFORM_ONLY_GUIDE.md](PLATFORM_ONLY_GUIDE.md)** - Platform-only trading mode
- **[BROKER_CONFIGURATION_GUIDE.md](BROKER_CONFIGURATION_GUIDE.md)** - Multi-broker setup
- **[.env.example](.env.example)** - Environment variable template
- **[MULTI_USER_PLATFORM_README.md](MULTI_USER_PLATFORM_README.md)** - Multi-user architecture

---

## Summary

**The ONE fix for hierarchy warnings:**

1. Get Kraken API credentials
2. Set `KRAKEN_PLATFORM_API_KEY` and `KRAKEN_PLATFORM_API_SECRET`
3. Restart the bot
4. Verify "✅ CONNECTED" status in logs

**Result:**
- ✅ Clean startup logs
- ✅ Stable operation
- ✅ Production-ready hierarchy
- ✅ No repeated warnings
- ✅ Linear, calm logs

**Platform account does not need capital - it just needs to exist and connect.**
