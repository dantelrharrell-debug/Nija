# NIJA Trading Bot - Broker Connection Troubleshooting Guide

## Quick Status Check

Run these commands to check your trading status:

```bash
# Check environment variables
python3 validate_all_env_vars.py

# Test broker connections
python3 check_trading_status.py
```

## Understanding Your Trading Status

### ✅ Bot CAN Trade If:
- **At least ONE master exchange is connected** (Coinbase, Kraken, OR Alpaca)
- The bot will trade on connected exchanges
- Failed exchanges are skipped automatically
- Trading continues independently on each working exchange

### ❌ Bot CANNOT Trade If:
- **NO master exchanges are connected**
- All connection attempts failed
- No valid API credentials configured

## Common Error Messages and Solutions

### 1. Kraken: "EGeneral:Permission denied"

**What it means:** Your Kraken API key lacks required permissions.

**Solution:**
1. Go to https://www.kraken.com/u/security/api
2. Find your API key and click "Edit"
3. Enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Save changes
5. Restart the bot

**Security Note:** Do NOT enable "Withdraw Funds" permission!

See also: `KRAKEN_PERMISSION_ERROR_FIX.md`

### 2. Kraken: "EAPI:Invalid nonce"

**What it means:** Timing/sequencing issue with Kraken API requests.

**Solutions:**
- **Usually self-healing**: The bot retries automatically with nonce adjustments
- **If persistent**:
  1. Wait 2-5 minutes for Kraken's nonce window to reset
  2. Restart the bot
  3. Check system clock is synchronized (use NTP)

**Technical Details:**
- The bot uses microsecond-precision nonces with monotonic guarantees
- Retries include nonce jumps to avoid conflicts
- Temporary lockout errors trigger longer delays (2-8 minutes)

### 3. Alpaca: "403 Forbidden" or "Too many errors"

**What it means:** API key is temporarily blocked due to too many errors.

**Solutions:**
1. Wait 5-10 minutes for the block to expire
2. Verify credentials are correct:
   - ALPACA_API_KEY
   - ALPACA_API_SECRET
   - ALPACA_PAPER (true for paper trading, false for live)
3. Check if paper trading is enabled on your account
4. Restart the bot after waiting

### 4. "No exchange credentials configured"

**What it means:** Environment variables are not set or not loaded.

**Solutions:**

#### If using .env file (local development):
1. Copy `.env.example` to `.env`
2. Fill in your API credentials
3. Ensure `.env` is in the same directory as `bot.py`
4. Restart the bot

#### If using Railway:
1. Go to your Railway project dashboard
2. Click on your service
3. Go to "Variables" tab
4. Add each environment variable:
   - Variable name: `COINBASE_API_KEY`
   - Value: Your API key
   - Click "Add"
5. Repeat for all required variables
6. Click "Deploy" to restart with new variables

#### If using Render:
1. Go to your Render dashboard
2. Select your Web Service
3. Go to "Environment" tab
4. Click "Add Environment Variable"
5. Add each required variable
6. Click "Save Changes"
7. Service will auto-deploy with new variables

### 5. "Credentials SET but EMPTY"

**What it means:** Environment variable exists but contains only whitespace.

**Solutions:**
1. Check for leading/trailing spaces in your .env file or platform dashboard
2. Remove any newlines or invisible characters
3. Ensure the value is not just whitespace
4. Example of CORRECT format:
   ```
   KRAKEN_MASTER_API_KEY=your-actual-api-key-here
   ```
   NOT:
   ```
   KRAKEN_MASTER_API_KEY=
   KRAKEN_MASTER_API_KEY=   
   ```

## Environment Variables Reference

### Coinbase (MASTER)
```bash
COINBASE_API_KEY=organizations/{org-id}/apiKeys/{key-id}
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END EC PRIVATE KEY-----"
```

### Kraken (MASTER)
```bash
KRAKEN_MASTER_API_KEY=your-kraken-api-key
KRAKEN_MASTER_API_SECRET=your-kraken-api-secret
```

Legacy format (also supported):
```bash
KRAKEN_API_KEY=your-kraken-api-key
KRAKEN_API_SECRET=your-kraken-api-secret
```

### Alpaca (MASTER)
```bash
ALPACA_API_KEY=your-alpaca-api-key
ALPACA_API_SECRET=your-alpaca-api-secret
ALPACA_PAPER=true  # or false for live trading
```

### User Accounts

#### Kraken Users
For user `daivon_frazier`:
```bash
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key
KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret
```

For user `tania_gilbert`:
```bash
KRAKEN_USER_TANIA_API_KEY=tania-api-key
KRAKEN_USER_TANIA_API_SECRET=tania-api-secret
```

#### Alpaca Users
For user `tania_gilbert`:
```bash
ALPACA_USER_TANIA_API_KEY=tania-alpaca-key
ALPACA_USER_TANIA_API_SECRET=tania-alpaca-secret
ALPACA_USER_TANIA_PAPER=true
```

**Pattern:** `{EXCHANGE}_USER_{FIRSTNAME}_{CREDENTIAL}`
where FIRSTNAME is extracted from user_id (part before first underscore, uppercase)

## Trading with Partial Exchange Connectivity

### How Multi-Exchange Trading Works

NIJA can trade on ANY subset of configured exchanges:

- **Scenario 1**: Only Coinbase connects → ✅ Trades on Coinbase
- **Scenario 2**: Coinbase + Alpaca connect, Kraken fails → ✅ Trades on Coinbase and Alpaca
- **Scenario 3**: All three connect → ✅ Trades on all three (best case)

### Independent Operation Mode

When `MULTI_BROKER_INDEPENDENT=true` (default):

- Each exchange runs in its own thread
- Failures on one exchange don't affect others
- Each exchange scans markets independently
- Position limits are per-exchange
- Trades execute simultaneously across exchanges

### What Happens When a Broker Fails

The bot will:
1. Log the failure with details
2. Continue with successfully connected brokers
3. Skip the failed broker for this session
4. Retry on next bot restart (not during runtime)

Example log output:
```
✅ Coinbase MASTER connected
❌ Kraken MASTER connection failed
✅ Alpaca MASTER connected
✅ NIJA CAN TRADE (2 of 3 exchanges active)
```

## Verifying Trading is Active

### Check 1: Startup Logs

Look for these messages in bot logs:
```
✅ NIJA CAN TRADE
Active Master Exchanges:
   ✅ Alpaca
   ✅ Coinbase
```

### Check 2: Market Scanning

You should see market scanning activity:
```
📊 Scanning 732 markets on Alpaca...
🔍 Found 12 potential opportunities
```

### Check 3: Position Updates

Watch for position management logs:
```
📊 Current positions: 3 / 7
💰 Available cash: $1,250.00
```

### Check 4: Trade Executions

Successful trades will log like this:
```
✅ BUY BTC-USD @ $43,250.00 (Size: $25.00)
Order ID: abc-123-xyz
```

## Debugging Steps

### Step 1: Validate Environment Variables
```bash
python3 validate_all_env_vars.py
```

Expected output:
- ✅ At least one master exchange shows "✅ Configured"
- Any ❌ will show specific fix instructions

### Step 2: Test Broker Connections
```bash
python3 check_trading_status.py
```

This attempts actual API connections and shows which brokers work.

### Step 3: Check Bot Startup
```bash
python3 bot.py
```

Watch the first 30 seconds of logs for connection messages.

### Step 4: Check Logs
```bash
tail -f nija.log
```

Look for:
- Exchange connection attempts
- Market scanning activity
- Trade signals and executions

## When to Seek Help

Contact support if you see:
- ✅ Environment variables are set correctly (verified by validation script)
- ✅ Broker connections succeed (verified by status check)
- ❌ But no trading activity after 1 hour
- ❌ Errors you don't understand
- ❌ Repeated connection failures despite correct credentials

Provide:
1. Output from `validate_all_env_vars.py`
2. Output from `check_trading_status.py`
3. Last 100 lines of `nija.log`
4. Platform (Railway/Render/Local)

## Best Practices

### For Reliability
1. **Enable multiple exchanges**: Don't rely on just one
2. **Use paper trading first**: Test with Alpaca paper mode
3. **Monitor logs regularly**: Check for errors
4. **Set up alerts**: Use your platform's log monitoring

### For Security
1. **Never share API secrets**: They give full account access
2. **Use read-only keys where possible**: For monitoring only
3. **Don't enable withdrawals**: Prevent fund theft
4. **Rotate keys periodically**: Update every 3-6 months

### For Performance
1. **Adequate balance**: Minimum $25 recommended per exchange
2. **Good network**: Bot needs reliable internet
3. **Keep bot running**: Don't restart frequently
4. **Monitor rate limits**: Especially on Coinbase

## Quick Reference: Deployment Platforms

### Railway
- Set variables: Dashboard → Service → Variables tab
- Restart: Dashboard → Service → "..." menu → "Restart Deployment"
- Logs: Dashboard → Service → "Deployments" → Click deployment → "View Logs"

### Render
- Set variables: Dashboard → Service → "Environment" tab
- Restart: Auto-deploys when you save variable changes
- Logs: Dashboard → Service → "Logs" tab

### Local Development
- Set variables: Create `.env` file in project root
- Restart: Stop bot (Ctrl+C) and run `python3 bot.py` again
- Logs: See terminal output or check `nija.log` file

## Additional Resources

- `GETTING_STARTED.md` - Initial setup guide
- `MULTI_EXCHANGE_TRADING_GUIDE.md` - Multi-exchange configuration
- `KRAKEN_PERMISSION_ERROR_FIX.md` - Fixing Kraken permissions
- `.env.example` - Template for environment variables
- `validate_all_env_vars.py` - Environment variable checker
- `check_trading_status.py` - Broker connection tester

## Summary

**Key Takeaway:** NIJA doesn't need ALL exchanges to work. It will trade on ANY exchanges that successfully connect. Focus on getting at least ONE master exchange (Coinbase, Kraken, or Alpaca) connected, and you're ready to trade!

**Quick Fix Checklist:**
- [ ] Run `python3 validate_all_env_vars.py`
- [ ] Fix any ❌ issues shown
- [ ] Run `python3 check_trading_status.py`
- [ ] Verify at least one ✅ exchange
- [ ] Restart bot with `python3 bot.py` or `bash start.sh`
- [ ] Watch logs for trading activity

**Still stuck?** The bot is designed to provide detailed error messages with fix instructions. Read the error carefully - it usually tells you exactly what to do!
