# Kraken Trading Setup Guide

## Overview

This guide explains how to enable Kraken trading for NIJA bot. Kraken trading is **already configured** in the code for:
- **Master Account** (NIJA system)
- **User #1** (Daivon Frazier)
- **User #2** (Tania Gilbert)

All that's needed is to add your Kraken API credentials.

## Quick Status Check

To check if Kraken is currently enabled, run:

```bash
python3 check_kraken_status.py
```

Or:

```bash
./check_kraken_status.sh
```

## Prerequisites

1. Active Kraken account(s) at https://www.kraken.com
2. API access enabled on your account(s)
3. Verified account with 2FA enabled (recommended)

## Step-by-Step Setup

### Step 1: Create Kraken API Keys

For each account (Master, User #1, User #2):

1. Log in to https://www.kraken.com
2. Navigate to **Settings** → **API**
3. Click **Generate New Key**
4. Set the following permissions:
   - ✅ **Query Funds** (view balances)
   - ✅ **Query Open Orders & Trades**
   - ✅ **Query Closed Orders & Trades**
   - ✅ **Create & Modify Orders** (place trades)
   - ✅ **Cancel/Close Orders**
5. Set a descriptive name (e.g., "NIJA Trading Bot - Master")
6. **Important**: Copy both the **API Key** and **Private Key** immediately
   - You won't be able to see the Private Key again
   - Store them securely (password manager recommended)

### Step 2: Configure Environment Variables

There are two methods depending on your deployment:

#### Method A: Local Development (`.env` file)

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your Kraken credentials:

   ```bash
   # MASTER ACCOUNT (NIJA system trading account)
   KRAKEN_MASTER_API_KEY=your-master-api-key-here
   KRAKEN_MASTER_API_SECRET=your-master-private-key-here
   
   # USER #1 (Daivon Frazier)
   KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
   KRAKEN_USER_DAIVON_API_SECRET=daivon-private-key-here
   
   # USER #2 (Tania Gilbert)
   KRAKEN_USER_TANIA_API_KEY=tania-api-key-here
   KRAKEN_USER_TANIA_API_SECRET=tania-private-key-here
   ```

3. **SECURITY**: Verify `.env` is in `.gitignore`:
   ```bash
   grep "^\.env$" .gitignore
   ```
   Should return: `.env`

4. **NEVER** commit `.env` to version control

#### Method B: Production Deployment (Railway/Render/etc.)

For Railway:
1. Go to your Railway project dashboard
2. Click on your service
3. Navigate to the **Variables** tab
4. Add each variable individually:
   - Variable: `KRAKEN_MASTER_API_KEY` → Value: `your-master-api-key`
   - Variable: `KRAKEN_MASTER_API_SECRET` → Value: `your-master-private-key`
   - Variable: `KRAKEN_USER_DAIVON_API_KEY` → Value: `daivon-api-key`
   - Variable: `KRAKEN_USER_DAIVON_API_SECRET` → Value: `daivon-private-key`
   - Variable: `KRAKEN_USER_TANIA_API_KEY` → Value: `tania-api-key`
   - Variable: `KRAKEN_USER_TANIA_API_SECRET` → Value: `tania-private-key`
5. Redeploy your service

For Render:
1. Go to your Render dashboard
2. Select your service
3. Go to **Environment** tab
4. Add each variable as a **Secret File** or **Environment Variable**
5. Redeploy

For Heroku:
```bash
heroku config:set KRAKEN_MASTER_API_KEY=your-master-api-key
heroku config:set KRAKEN_MASTER_API_SECRET=your-master-private-key
heroku config:set KRAKEN_USER_DAIVON_API_KEY=daivon-api-key
heroku config:set KRAKEN_USER_DAIVON_API_SECRET=daivon-private-key
heroku config:set KRAKEN_USER_TANIA_API_KEY=tania-api-key
heroku config:set KRAKEN_USER_TANIA_API_SECRET=tania-private-key
```

### Step 3: Verify Configuration

1. **Start the bot**:
   ```bash
   ./start.sh
   ```

2. **Check the logs** for Kraken connection messages:
   ```
   📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
   ✅ Connected to Kraken Pro API (MASTER)
   💰 Kraken MASTER balance: $XXX.XX
   
   👤 CONNECTING USER ACCOUNTS
   📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $XXX.XX
   
   📊 Attempting to connect User #2 (Tania Gilbert) - Kraken...
   ✅ User #2 Kraken connected
   💰 User #2 Kraken balance: $XXX.XX
   ```

3. **Run status check**:
   ```bash
   python3 check_kraken_status.py
   ```
   
   Expected output:
   ```
   ✅ Master account: CONNECTED to Kraken
   ✅ User #1 (Daivon Frazier): CONNECTED to Kraken
   ✅ User #2 (Tania Gilbert): CONNECTED to Kraken
   
   Configured Accounts: 3/3
   ```

### Step 4: Test Trading (Optional but Recommended)

Before live trading with large amounts:

1. **Test with small positions first**:
   - Start with minimum position sizes ($5-10)
   - Verify orders execute correctly
   - Check that balances update properly

2. **Monitor for errors**:
   - Watch logs for any API errors
   - Verify nonce issues are resolved (should be fixed in current code)
   - Check that all three accounts can trade independently

3. **Verify independent operation**:
   - Each account should trade independently
   - Errors in one account shouldn't affect others
   - Balances should be tracked separately

## Troubleshooting

### Issue: "Kraken credentials not configured"

**Symptom**: Logs show:
```
⚠️  Kraken credentials not configured for MASTER (skipping)
   To enable Kraken MASTER trading, set:
      KRAKEN_MASTER_API_KEY=<your-api-key>
      KRAKEN_MASTER_API_SECRET=<your-api-secret>
```

**Solution**:
1. Double-check environment variables are set correctly
2. Verify variable names match exactly (case-sensitive)
3. Restart the bot after setting variables
4. For Railway/Render: verify variables are set in dashboard and redeployed

### Issue: "Invalid nonce" errors

**Symptom**: API errors mentioning invalid or duplicate nonce

**Solution**: Already fixed in current code! The bot includes:
- Random offset on nonce initialization (prevents collisions between accounts)
- Strict monotonic increase guarantee (prevents duplicates)
- Thread-safe nonce generation (prevents race conditions)
- 3-second delays between user connections

If you still see this error:
1. Make sure you're running the latest code
2. Check that no other applications are using the same API keys
3. Verify system clock is synchronized (use NTP)

### Issue: "Permission denied" errors

**Symptom**: Orders fail with permission errors

**Solution**:
1. Go to https://www.kraken.com/u/security/api
2. Edit your API key
3. Verify all required permissions are enabled:
   - Query Funds ✅
   - Query Orders ✅
   - Create Orders ✅
   - Cancel Orders ✅

### Issue: One account works but others don't

**Symptom**: Master connects but users don't, or vice versa

**Solution**:
1. Check that environment variable names match exactly:
   - `KRAKEN_USER_DAIVON_API_KEY` (note: DAIVON not DAIVON_FRAZIER)
   - `KRAKEN_USER_TANIA_API_KEY` (note: TANIA not TANIA_GILBERT)
2. The bot extracts the first name from user_id for environment variables
3. User IDs: `daivon_frazier` → env var: `DAIVON`
4. User IDs: `tania_gilbert` → env var: `TANIA`

### Issue: Bot starts but no trades on Kraken

**Possible causes**:
1. **Insufficient balance**: Check minimum balance requirements
2. **Market conditions**: Bot only trades when RSI signals align
3. **Rate limiting**: Bot may be throttling API calls
4. **Permissions**: Verify API keys can create orders

**Check**:
```bash
# View recent logs
tail -f nija.log

# Check balances
python3 -c "from bot.broker_manager import KrakenBroker, AccountType; k = KrakenBroker(AccountType.MASTER); k.connect(); print(f'Balance: ${k.get_account_balance()}')"
```

## Security Best Practices

1. **Never commit credentials**:
   - ✅ `.env` is in `.gitignore`
   - ✅ Never paste keys in code files
   - ✅ Use environment variables or secrets managers

2. **Use API key restrictions**:
   - Enable IP whitelisting if possible
   - Set expiration dates on API keys
   - Use separate keys for testing vs production

3. **Enable 2FA**:
   - Always enable 2FA on Kraken accounts
   - Use authenticator apps (not SMS)

4. **Regular key rotation**:
   - Rotate API keys every 3-6 months
   - Immediately rotate if keys are compromised
   - Keep backup of old keys for 30 days

5. **Monitor access**:
   - Review API key usage in Kraken dashboard
   - Set up alerts for unusual activity
   - Monitor account balances daily

## Additional Resources

- **Kraken API Documentation**: https://docs.kraken.com/rest/
- **API Key Management**: https://support.kraken.com/hc/en-us/articles/360000919966
- **NIJA Documentation**:
  - `KRAKEN_CONNECTION_STATUS.md` - Detailed connection status
  - `KRAKEN_NONCE_IMPROVEMENTS.md` - Technical implementation details
  - `MULTI_USER_SETUP_GUIDE.md` - User management
  - `IS_KRAKEN_CONNECTED.md` - Quick reference

## Frequently Asked Questions

**Q: Do I need separate Kraken accounts for each user?**  
A: Yes, each user (Master, User #1, User #2) should have their own Kraken account with separate API keys.

**Q: Can I use the same API key for multiple users?**  
A: No, this will cause nonce collision errors and trading conflicts. Each user needs separate credentials.

**Q: What happens if I don't set up all three accounts?**  
A: The bot will gracefully skip accounts without credentials. For example, if you only set up Master, it will trade on Master and skip the users.

**Q: Is Kraken required for NIJA to work?**  
A: No, Kraken is optional. NIJA supports multiple brokers (Coinbase, Alpaca, Binance, OKX, etc.). You can use any combination.

**Q: Can I disable Kraken trading after enabling it?**  
A: Yes, just remove or comment out the Kraken environment variables and restart the bot.

**Q: What are the minimum balance requirements for Kraken?**  
A: The bot requires a minimum of $1.00 to start (configurable), but $25+ is recommended for effective trading after fees.

## Summary

To enable Kraken trading:

1. ✅ **Code is ready** - No code changes needed!
2. 🔑 **Get API keys** from https://www.kraken.com/u/security/api
3. ⚙️ **Set environment variables** (6 variables total: 2 per account)
4. 🔄 **Restart bot** - ./start.sh
5. ✅ **Verify** - Run check_kraken_status.py

That's it! Kraken trading will be active for all configured accounts.

---

**Last Updated**: January 12, 2026  
**Status**: Kraken Integration Ready  
**Required Action**: Add API credentials to enable trading
