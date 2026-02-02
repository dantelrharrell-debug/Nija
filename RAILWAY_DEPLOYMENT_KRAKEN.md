# Railway Deployment Guide - Kraken Platform API Keys

This guide covers deploying NIJA with Kraken Platform API credentials to Railway.

## 🔑 Critical Environment Variables

### Required Kraken Platform Keys

```bash
KRAKEN_PLATFORM_API_KEY=<your-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-api-secret>
```

**Important Notes:**
- These are the **PRIMARY** API keys for the platform/master account
- Must use "Classic API Key" format (NOT OAuth or App keys)
- Get credentials from: https://www.kraken.com/u/security/api

### Required Permissions

When creating your Kraken API key, enable these permissions:
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders
- ❌ Do NOT enable "Withdraw Funds" (security best practice)

## 🚀 Railway Deployment Steps

### Step 1: Set Environment Variables in Railway

1. Go to your Railway project dashboard
2. Click on your service
3. Navigate to the **Variables** tab
4. Add the following variables:

```bash
# Kraken Platform Credentials (REQUIRED)
KRAKEN_PLATFORM_API_KEY=<paste-your-api-key-here>
KRAKEN_PLATFORM_API_SECRET=<paste-your-api-secret-here>

# Safety Settings
LIVE_CAPITAL_VERIFIED=false    # Set to 'true' only when ready for live trading
PRO_MODE=true                   # Enable position rotation trading
HEARTBEAT_TRADE=false           # Set to 'true' for initial verification (see below)

# Trading Configuration
LIVE_TRADING=1
MIN_CASH_TO_BUY=5.50
MINIMUM_TRADING_BALANCE=25.0
MAX_CONCURRENT_POSITIONS=7

# Optional: Platform Account Tier
PLATFORM_ACCOUNT_TIER=BALLER   # Force BALLER tier for best risk management
```

### Step 2: Verify Connection (Optional but Recommended)

Before enabling live trading, verify your API credentials work:

1. Set `HEARTBEAT_TRADE=true` in Railway variables
2. Deploy/redeploy the service
3. Check logs - you should see:
   ```
   💓 HEARTBEAT TRADE MODE ACTIVATED
   ✅ Heartbeat buy order placed successfully
   ✅ Heartbeat position closed successfully
   💓 HEARTBEAT TRADE VERIFICATION: ✅ SUCCESS
   ```
4. **IMPORTANT:** After heartbeat succeeds, set `HEARTBEAT_TRADE=false`
5. Redeploy to resume normal trading

### Step 3: Enable Live Trading

Once you've verified credentials:

1. Set `LIVE_CAPITAL_VERIFIED=true` in Railway
2. Ensure `HEARTBEAT_TRADE=false`
3. Deploy/redeploy the service
4. Monitor logs to confirm trading starts

## 📊 Trust Layer Features

### User Status Banner

On startup, you'll see a comprehensive status banner:

```
===============================================================
🧠 TRUST LAYER - USER STATUS BANNER
===============================================================
📋 SAFETY SETTINGS:
   • LIVE_CAPITAL_VERIFIED: ✅ TRUE
   • PRO_MODE: ✅ ENABLED
   • HEARTBEAT_TRADE: ❌ DISABLED

📊 PLATFORM ACCOUNT:
   • Broker: KRAKEN
   • Balance: $XXX.XX
   • Status: ✅ CONNECTED

👥 USER ACCOUNTS:
   • No user accounts configured
===============================================================
```

### Trade Veto Logging

When trades are blocked, you'll see explicit veto reasons:

```
======================================================================
🚫 TRADE VETO - Signal Blocked from Execution
======================================================================
   Veto Reason 1: Position cap reached (7/7)
   Veto Reason 2: Insufficient balance ($15.00 < $25.00)
======================================================================
```

This helps diagnose why trades aren't executing.

## 🔍 Verification Checklist

After deployment, verify these in the Railway logs:

- [ ] `✅ Kraken PLATFORM connected`
- [ ] `💰 LIVE MULTI-BROKER CAPITAL BREAKDOWN` shows correct balance
- [ ] `📊 PLATFORM ACCOUNT: TRADING (Broker: KRAKEN)`
- [ ] `🚀 TRADING ACTIVE: 1 account(s) ready`
- [ ] No error messages about missing credentials
- [ ] No `❌ TRADE VETO` messages (unless expected)

## 🛡️ Security Best Practices

1. **Never commit API keys to Git**
   - Always use Railway environment variables
   - Never paste keys in code or config files

2. **Use separate API keys for testing**
   - Create a test key for heartbeat verification
   - Use a different key for production trading

3. **Monitor API key permissions**
   - Regularly review active API keys in Kraken dashboard
   - Revoke old/unused keys immediately

4. **Set up IP whitelisting (optional)**
   - Kraken allows IP whitelisting for API keys
   - Add Railway's egress IPs for extra security

## 🐛 Troubleshooting

### Issue: `❌ CRITICAL: Kraken Platform credentials are REQUIRED`

**Solution:** Set both `KRAKEN_PLATFORM_API_KEY` and `KRAKEN_PLATFORM_API_SECRET` in Railway variables.

### Issue: `⚠️ Kraken PLATFORM connection test failed`

**Possible causes:**
1. Invalid API key/secret
2. Insufficient permissions on API key
3. Network timeout (temporary)

**Solution:**
1. Verify API key in Kraken dashboard
2. Check all required permissions are enabled
3. Try redeploying after a few minutes

### Issue: Heartbeat trade fails

**Check logs for specific error:**
- Balance too low? Fund account with at least $25
- API permissions? Ensure "Create & Modify Orders" is enabled
- Network issues? Retry after a few minutes

### Issue: No trades executing despite `✅ CONNECTED`

**Check for trade veto messages:**
```bash
🚫 TRADE VETO - Signal Blocked from Execution
```

Common veto reasons:
- `LIVE_CAPITAL_VERIFIED=false` - Must be set to `true`
- Insufficient balance below minimum
- Position cap reached
- Market conditions don't meet strategy criteria

## 📞 Support

For issues specific to:
- **Kraken API:** https://support.kraken.com/
- **Railway Deployment:** https://docs.railway.app/
- **NIJA Bot:** Check repository README and documentation

## 🎯 Next Steps

After successful deployment:

1. Monitor first few trades closely
2. Check position management is working
3. Verify profit targets and stop losses execute
4. Review trade logs for quality

**Remember:** Start small, monitor closely, scale gradually.
