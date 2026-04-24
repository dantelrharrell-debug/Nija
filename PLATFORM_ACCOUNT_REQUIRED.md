# Platform Account Configuration - Required for Full Operation

**Version:** 1.2  
**Last Updated:** March 2026  
**Status:** REQUIRED — without Platform account, new entries are blocked (standalone mode)

---

## The ONE Fix for Full Trading Operation

### Current Behavior (Platform Account Missing)

When running NIJA with only user accounts (no Platform account), you will see:

- ⚠️  **Hierarchy warnings** about Platform account not connected
- 🔒  **Standalone mode enforced** — new entries are **blocked** for affected users
- ✅  **Exit cycles run normally** — NIJA continues managing existing positions for profit exits and risk
- ℹ️  **Step-by-step instructions** to restore full trading

### How to Restore Full Trading

**Step 1: Connect Platform Kraken Account**

Set the following environment variables for your Platform Kraken account:

```bash
KRAKEN_PLATFORM_API_KEY=<your-platform-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-platform-api-secret>
```

**Step 2: Restart NIJA**

After setting the variables, restart the bot:

```bash
./start.sh
```

**Result:**
- ✅ New entries will resume immediately
- ✅ Hierarchy warnings will clear
- ✅ Platform becomes PRIMARY, users become SECONDARY
- ✅ Unified reporting and capital protection fully enabled

**Step 3: Monitor Exit Cycles**

While you are in standalone mode (before Platform account is connected), NIJA
automatically manages your existing positions for profit exits and risk:

- 🔄 Stop-loss orders are enforced
- 🎯 Take-profit targets are tracked
- 📈 Trailing stops are active
- ⚠️  No new entries will be opened

---

## Understanding Standalone Mode

When the Platform account is **not** connected and a user account **is** connected,
NIJA automatically enforces **standalone mode** (RECOVERY) for the affected user:

```
⚠️  HIERARCHY ISSUE — STANDALONE MODE ACTIVE
   Platform account NOT connected: KRAKEN
   User accounts are temporarily acting as primary.
   🔒 NEW ENTRIES BLOCKED (exits still work).
      Connect the Platform account first, then configure users as secondary.
```

**Standalone mode means:**
- ❌ No new trade entries will be accepted
- ✅ Existing positions continue to be managed (exits, stops, take-profits)
- ✅ The bot runs exit cycles every 2.5 minutes automatically

This protects capital and prevents incorrect exposure while the hierarchy is misconfigured.

---

## Understanding the Architecture

### Primary / Secondary Structure

NIJA enforces a strict account hierarchy:

```
🔷 PLATFORM ACCOUNT (PRIMARY)
   ↓ Must be connected first
   ↓ Routes trades and maintains correct exposure limits
   ↓ Enables unified reporting and risk aggregation
   ↓ Enables capital orchestration

👤 USER ACCOUNT (SECONDARY)
   ↓ Connects after Platform
   ↓ Adopts positions and risk limits from Platform context
   ↓ Trades with its own capital under Platform oversight
```

**Without Platform account:**
- ❌ Risk aggregation is incomplete
- ❌ Capital orchestration is unavailable
- ❌ Reporting may be inconsistent
- ❌ New entries are blocked (standalone/RECOVERY mode)
- ✅ Exit management still works

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
# Platform Kraken credentials (REQUIRED for new entries)
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
✅ HIERARCHY VALID: Platform is PRIMARY, all users are SECONDARY
```

**❌ Still in standalone mode?**
```
⚠️  HIERARCHY ISSUE — STANDALONE MODE ACTIVE
   Platform account NOT connected: KRAKEN
   🔒 NEW ENTRIES BLOCKED (exits still work).
```

If you see warnings, verify:
1. Environment variables are spelled correctly (case-sensitive)
2. No leading/trailing whitespace in credential values
3. Deployment platform has restarted after setting variables
4. API credentials are valid (check Kraken dashboard)

---

## Frequently Asked Questions

### Q: Is Platform account required?

**A:** Yes, for new entries. Without Platform account:
- ✅ Existing positions are managed (exits, stops, take-profits)
- 🔒 No new entries are accepted (standalone/RECOVERY mode enforced automatically)
- ⚠️  Risk aggregation and capital orchestration are unavailable

For full trading capability, **Platform account is required**.

### Q: What happens to my existing positions while in standalone mode?

**A:** NIJA continues to manage them automatically:
- 🔄 Stop-loss orders are enforced
- 🎯 Take-profit targets are tracked  
- 📈 Trailing stops are active
- ⏱️  Exit cycles run every 2.5 minutes

### Q: Will configuring Platform account change my existing user account trading?

**A:** No disruption to existing positions. Platform account connection:
- Restores new entry capability for users
- Enables unified reporting and risk aggregation
- Enables capital orchestration
- Resolves hierarchy warnings

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
- ✅ Configure `KRAKEN_PLATFORM_API_KEY/SECRET` (required for new entries)
- ❌ Don't need Alpaca Platform credentials

**Scenario B: User accounts on Kraken AND Alpaca**
- ✅ Configure `KRAKEN_PLATFORM_API_KEY/SECRET` (required)
- ✅ Configure `ALPACA_API_KEY/SECRET` (Platform account, required)

### Q: What if Platform account connection fails?

**A:** Check logs for specific errors:
- Invalid credentials → Verify in Kraken dashboard
- Whitespace in credentials → Re-paste without extra spaces
- Wrong permission → Enable required API permissions
- Network issues → Check Kraken API status

System will continue attempting connection and display warnings until Platform account connects successfully. Users remain in standalone mode (exits only) until Platform connects.

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

## Quick Reference

### Restore Full Trading in 3 Steps

```
1. Set KRAKEN_PLATFORM_API_KEY=<key>
2. Set KRAKEN_PLATFORM_API_SECRET=<secret>
3. Restart NIJA
```

**Result:**
- ✅ New entries resume
- ✅ Hierarchy warnings clear
- ✅ Platform PRIMARY, users SECONDARY
- ✅ Full reporting and risk aggregation active

### While in Standalone Mode

NIJA automatically monitors your existing positions:

- ✅ Exit cycles run every 2.5 minutes
- ✅ Stop-loss protection active
- ✅ Take-profit targets tracked
- ✅ Trailing stops enforced
- 🔒 No new entries until Platform account connected
