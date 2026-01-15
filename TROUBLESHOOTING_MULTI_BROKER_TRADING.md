# Troubleshooting Multi-Broker Trading

## Problem: Only Coinbase Master Is Trading

If you're seeing that credentials are configured for multiple exchanges (Coinbase, Kraken, OKX, etc.) but only Coinbase Master is actively trading, this guide will help you diagnose and fix the issue.

## Quick Diagnostic

Run the diagnostic script to identify the problem:

```bash
python3 diagnose_multi_broker_trading.py
```

This script checks:
- ✅ Which exchange credentials are configured
- ✅ Which exchanges can connect
- ✅ Account balances on each exchange  
- ✅ Which accounts are funded (≥ $1.00)
- ✅ Whether independent trading mode is enabled
- ✅ Provides specific recommendations

## Common Issues & Solutions

### Issue 1: Independent Trading Mode Disabled

**Symptoms:**
- Multiple exchanges show as "connected" in logs
- Only Coinbase Master executes trades
- No "STARTING INDEPENDENT MULTI-BROKER TRADING MODE" in logs

**Diagnosis:**
```bash
# Check if the env var is set
echo $MULTI_BROKER_INDEPENDENT
```

**Fix:**
1. Set the environment variable to enable multi-broker trading:

   **Railway:**
   ```
   Dashboard → Service → Variables → Add Variable
   Name: MULTI_BROKER_INDEPENDENT
   Value: true
   ```

   **Render:**
   ```
   Dashboard → Service → Environment → Add Environment Variable
   Key: MULTI_BROKER_INDEPENDENT
   Value: true
   ```

   **Local (.env file):**
   ```bash
   echo "MULTI_BROKER_INDEPENDENT=true" >> .env
   ```

2. Restart the bot
3. Look for this log message:
   ```
   🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE
   Each broker will trade independently in isolated threads.
   ```

### Issue 2: Exchanges Not Funded

**Symptoms:**
- Exchanges connect successfully
- But trading threads don't start for those exchanges
- Logs show "⚠️  Underfunded (minimum: $1.00)"

**Diagnosis:**
```bash
python3 diagnose_multi_broker_trading.py
```
Look for the "💰 CHECKING FUNDED STATUS" section.

**Fix:**
1. Fund the exchange account with at least $1.00 (recommend $25+ for profitable trading)
2. Wait 2-5 minutes for balance to sync
3. Restart the bot
4. Verify with diagnostic script

### Issue 3: Exchange Connection Failures

**Symptoms:**
- Credentials are configured
- Exchange shows "❌ Connection failed" in diagnostic
- Specific error messages for that exchange

**Common Causes & Fixes:**

**Kraken:**
- **Permission Error:** API key doesn't have required permissions
  - Fix: Go to https://www.kraken.com/u/security/api
  - Enable: Query Funds, Create Orders, Cancel Orders, Query Orders
  - See `KRAKEN_PERMISSION_ERROR_FIX.md`

- **Nonce Error:** Invalid nonce or clock sync issues
  - The bot has automatic nonce handling
  - If persistent, see `KRAKEN_NONCE_FIX_SUMMARY.md`

- **Whitespace in Credentials:** Credentials contain only whitespace
  - Check Railway/Render dashboard for extra spaces/newlines
  - Re-paste credentials carefully
  - See `KRAKEN_CREDENTIAL_TROUBLESHOOTING.md`

**OKX:**
- **Invalid Passphrase:** Placeholder value like "your_passphrase"
  - Fix: Set real OKX API passphrase from https://www.okx.com/account/my-api

**Coinbase:**
- **Consumer Wallet Funds:** Money in Coinbase wallet, not Advanced Trade
  - Fix: Transfer funds to Advanced Trade portfolio
  - URL: https://www.coinbase.com/advanced-portfolio

### Issue 4: Trading Threads Not Starting

**Symptoms:**
- Independent trading mode is enabled
- Exchanges are funded
- But no "Started independent trading thread for..." messages in logs

**Diagnosis:**
1. Check bot startup logs for the "STARTING INDEPENDENT MULTI-BROKER TRADING MODE" section
2. Look for these specific messages:
   ```
   ✅ Started independent trading thread for coinbase (MASTER)
   ✅ Started independent trading thread for kraken (MASTER)
   ✅ Started independent trading thread for okx (MASTER)
   ```

**Fix:**
1. Verify `independent_trader` initialized:
   ```
   # In logs, look for:
   ✅ Independent broker trader initialized
   ```
   
2. If missing, there may be an import error. Check logs for:
   ```
   ⚠️  Independent trader initialization failed: ...
   ```

3. If threads start but immediately stop, check for balance/API errors specific to each exchange

### Issue 5: User Account Trading Not Working

**Symptoms:**
- Master accounts trading but user accounts (Daivon, Tania) are not
- User credentials are configured
- User balances are sufficient

**Diagnosis:**
```bash
python3 diagnose_multi_broker_trading.py
```
Look for "USER ACCOUNTS" section.

**Fix:**
1. Verify user config files exist:
   ```bash
   ls -la config/users/
   ```
   
2. Check if users are marked as enabled in their config files:
   ```bash
   cat config/users/daivon_frazier.json
   cat config/users/tania_gilbert.json
   ```
   
3. Ensure `"enabled": true` in each user's JSON config

4. Verify user broker threads start:
   ```
   # Look for in logs:
   ✅ Started independent trading thread for daivon_frazier_kraken (USER)
   ✅ Started independent trading thread for tania_gilbert_kraken (USER)
   ```

## Verification Checklist

After applying fixes, verify multi-broker trading is working:

- [ ] Run `python3 diagnose_multi_broker_trading.py` - all checks pass
- [ ] Bot logs show: `🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE`
- [ ] Logs show trading thread started for each funded exchange:
  - [ ] `✅ Started independent trading thread for coinbase (MASTER)`
  - [ ] `✅ Started independent trading thread for kraken (MASTER)`
  - [ ] `✅ Started independent trading thread for okx (MASTER)`
  - [ ] `✅ Started independent trading thread for daivon_frazier_kraken (USER)` (if configured)
  - [ ] `✅ Started independent trading thread for tania_gilbert_kraken (USER)` (if configured)
- [ ] Logs show cycle messages for each exchange:
  - [ ] `🔄 coinbase - Cycle #1`
  - [ ] `🔄 kraken - Cycle #1`
  - [ ] `🔄 okx - Cycle #1`
- [ ] No permission/nonce errors for any exchange
- [ ] Trades appear on multiple exchanges (check exchange dashboards)

## Understanding Independent Multi-Broker Trading

NIJA's independent multi-broker system works as follows:

### Architecture
- **Master Account:** NIJA system trading account
  - Can connect to: Coinbase, Kraken, OKX, Binance
  - Trades independently from user accounts
  
- **User Accounts:** Individual investor accounts
  - Currently supported for Kraken and Alpaca
  - Each user trades completely independently
  - User #1 doesn't affect User #2
  - Users don't affect Master

### Key Principles

1. **Complete Independence:** Each exchange operates in its own isolated thread
   - Coinbase failure → Kraken/OKX keep trading
   - Kraken nonce error → doesn't affect Coinbase/OKX
   - OKX rate limit → doesn't cascade to others

2. **Separate Balance Tracking:** Each account manages its own capital
   - Master balance ≠ User balances
   - Each exchange has its own position limits
   - Capital allocation is independent per exchange

3. **Isolated Errors:** Failures don't cascade
   - Thread crashes are contained
   - API errors are exchange-specific
   - One broker's issues don't block others

### How It Works

1. **Startup:** Bot connects to all configured and funded exchanges
   
2. **Detection:** `detect_funded_brokers()` finds accounts with ≥ $1.00
   
3. **Thread Creation:** One thread per funded exchange
   ```
   Thread-1: Coinbase Master (2.5 min cycle)
   Thread-2: Kraken Master (2.5 min cycle)
   Thread-3: OKX Master (2.5 min cycle)
   Thread-4: daivon_frazier_kraken (2.5 min cycle)
   Thread-5: tania_gilbert_kraken (2.5 min cycle)
   ```
   
4. **Independent Execution:** Each thread runs `run_cycle(broker=...)` independently
   - Scans markets for its exchange
   - Places orders on its exchange
   - Manages positions on its exchange
   - Cycles every 2.5 minutes
   
5. **Health Monitoring:** Main thread monitors all trading threads
   - Logs status every 25 minutes
   - Detects and reports errors
   - Continues even if some threads fail

## Advanced Debugging

### Check Running Threads

If the bot is running, you can check active threads:

```bash
# In another terminal, attach to the running container (Railway/Render)
# or if running locally:
ps aux | grep python
```

Look for multiple Python processes or check logs for thread IDs.

### Enable Debug Logging

Add to environment:
```
LOG_LEVEL=DEBUG
```

This will show detailed information about:
- Broker initialization
- Thread creation
- Cycle execution
- Balance checks
- API calls

### Manual Thread Test

Test if individual exchanges can trade:

```python
# Test Kraken independently
python3 test_kraken_connection_live.py

# Test OKX (create similar test script if needed)
```

## Getting Help

If multi-broker trading still isn't working after following this guide:

1. **Collect Information:**
   ```bash
   # Run diagnostic
   python3 diagnose_multi_broker_trading.py > diagnostic_output.txt
   
   # Get recent logs
   tail -n 500 nija.log > recent_logs.txt
   
   # Check environment
   env | grep -E "(COINBASE|KRAKEN|OKX|MULTI_BROKER)" > env_vars.txt
   ```

2. **Check Related Guides:**
   - `MULTI_EXCHANGE_TRADING_GUIDE.md` - General multi-exchange setup
   - `KRAKEN_NOT_CONNECTING_DIAGNOSIS.md` - Kraken-specific issues
   - `KRAKEN_PERMISSION_ERROR_FIX.md` - Kraken API permission problems
   - `SOLUTION_ENABLE_EXCHANGES.md` - How to enable additional exchanges

3. **Review Recent Changes:**
   - Check if environment variables changed
   - Verify no recent code changes broke multi-broker logic
   - Confirm no account balances dropped below $1.00

4. **Restart Deployment:**
   - Railway: Dashboard → Service → "..." → Restart
   - Render: Dashboard → Service → Manual Deploy
   - Local: Stop bot (Ctrl+C) and restart: `./start.sh`

## Technical Details

### Minimum Balance Requirements

- **Hard Minimum:** $1.00 (allows trading to start)
- **Recommended Minimum:** $25.00 (for profitable trading after fees)
- **Why?** Coinbase/exchange fees are ~1.4% round-trip
  - $1.00 position → ~$0.014 fees → limited profit potential
  - $25.00 position → ~$0.35 fees → reasonable profit potential

### Thread Staggering

The bot staggers thread starts by 10 seconds to prevent:
- Concurrent API bursts (rate limiting)
- Nonce collisions (Kraken)
- Resource contention

### Environment Variables Reference

```bash
# Enable/disable multi-broker trading
MULTI_BROKER_INDEPENDENT=true  # (default: true)

# Exchange credentials (Master accounts)
COINBASE_API_KEY=...
COINBASE_API_SECRET=...

KRAKEN_MASTER_API_KEY=...
KRAKEN_MASTER_API_SECRET=...

OKX_API_KEY=...
OKX_API_SECRET=...
OKX_PASSPHRASE=...

# Exchange credentials (User accounts)
KRAKEN_USER_DAIVON_API_KEY=...
KRAKEN_USER_DAIVON_API_SECRET=...

KRAKEN_USER_TANIA_API_KEY=...
KRAKEN_USER_TANIA_API_SECRET=...

ALPACA_USER_TANIA_API_KEY=...
ALPACA_USER_TANIA_API_SECRET=...
ALPACA_USER_TANIA_PAPER=true  # (default: true for testing)
```

### Default Behavior

If `MULTI_BROKER_INDEPENDENT` is not set:
- **Defaults to:** `true` (multi-broker mode enabled)
- **Falls back to:** Single-broker mode if independent trader fails to initialize
- **Primary broker:** First connected broker (usually Coinbase)

## Summary

The most common reasons for "only Coinbase trading" are:

1. ✅ **Independent trading disabled** → Set `MULTI_BROKER_INDEPENDENT=true`
2. ✅ **Exchanges underfunded** → Fund accounts with ≥ $1.00
3. ✅ **Connection failures** → Check credentials and permissions
4. ✅ **User accounts not enabled** → Check config files

Run `python3 diagnose_multi_broker_trading.py` to identify which applies to your situation.

---

## Issue: "NO FUNDED BROKERS DETECTED" Despite Having Funds

### Symptoms
- Bot shows "NO FUNDED USER BROKERS DETECTED" or "NO FUNDED BROKERS DETECTED"
- Falls back to single-broker mode
- You know you have funds in your Coinbase account

### Root Cause
Coinbase Advanced Trade API can return a stale/cached $0 balance immediately after connection due to API-side caching. This was particularly problematic for user broker accounts which had no retry logic.

### Solution (Implemented Jan 15, 2026)
The bot now has enhanced balance detection with:
- **3 retry attempts** with increasing delays (2s, 4s, 6s) for Coinbase
- **Cache clearing** before each retry to force fresh API calls
- **Improved logging** showing retry progress and diagnostics
- **User broker support** - user accounts now get same retry logic as master

### What to Look For in Logs

**Successful Balance Detection:**
```
🔍 Detecting funded brokers...
   💰 coinbase: $123.45
      ✅ FUNDED - Ready to trade
✅ FUNDED BROKERS: 1
💰 TOTAL TRADING CAPITAL: $123.45
```

**Balance Detection with Retries:**
```
🔍 Detecting funded brokers...
   Coinbase returned $0.00, retrying with delays to bypass API cache...
   Retry #1/3: waiting 2s before retry...
   Cache cleared, fetching fresh balance...
   Retry #1/3 returned: $123.45
   ✅ Balance detected after retry #1/3
   💰 coinbase: $123.45
      ✅ FUNDED - Ready to trade
```

**Truly Unfunded Account:**
```
🔍 Detecting funded brokers...
   Coinbase returned $0.00, retrying with delays to bypass API cache...
   Retry #1/3: waiting 2s before retry...
   Retry #2/3: waiting 4s before retry...
   Retry #3/3: waiting 6s before retry...
   ⚠️  All 3 retries exhausted, balance still $0.00
   This likely means:
      1. No funds in Advanced Trade portfolio
      2. Funds may be in Consumer wallet (not API-accessible)
      3. Transfer funds: https://www.coinbase.com/advanced-portfolio
   💰 coinbase: $0.00
      ⚠️  Underfunded (minimum: $1.00)
⚠️  NO FUNDED BROKERS DETECTED
```

### If Balance Still Shows $0 After Retries

1. **Check Advanced Trade Portfolio:**
   - Visit: https://www.coinbase.com/advanced-portfolio
   - Verify you have USD or USDC balance there (not in Consumer wallet)
   - Minimum required: $1.00

2. **Check Consumer Wallet:**
   - Coinbase has two types of wallets:
     - **Consumer Wallet**: Used for buying/selling crypto on Coinbase.com
     - **Advanced Trade Portfolio**: Used for API trading
   - Funds in Consumer wallet CANNOT be used for bot trading
   - You must manually transfer funds from Consumer → Advanced Trade
   
   **To Transfer:**
   - Go to: https://www.coinbase.com/advanced-portfolio
   - Click "Deposit" or "Transfer"
   - Select amount and confirm transfer
   - Wait 1-2 minutes for transfer to complete
   - Restart the bot

3. **Verify API Permissions:**
   - Go to: https://portal.cloud.coinbase.com/access/api
   - Ensure your API key has "View" permission
   - Ensure API key is not expired or disabled

4. **Check API Credentials:**
   ```bash
   # Verify environment variables are set
   echo $COINBASE_API_KEY
   echo $COINBASE_API_SECRET
   ```
   - Both should show values (not empty)
   - Check for typos or extra whitespace

### Testing the Fix

**Manual Test:**
```bash
python3 test_balance_detection.py
```

This will:
- Connect to Coinbase
- Fetch balance immediately
- Retry after delays with cache clearing
- Show detailed balance information

**Diagnostic Test:**
```bash
python3 diagnose_multi_broker_trading.py
```

This will:
- Check all exchange credentials
- Test connections
- Show balances
- Identify funded accounts
- Provide specific recommendations

### Technical Details

**Files Modified:**
- `bot/independent_broker_trader.py` - Enhanced retry logic
- `bot/broker_manager.py` - Added `clear_cache()` method

**Key Changes:**
- Created `_retry_coinbase_balance_if_zero()` helper method
- Enhanced `detect_funded_brokers()` with retry logic
- Added retry logic to `detect_funded_user_brokers()` (was missing)
- Retry timing: 2s + 4s + 6s = 12 seconds total max
- Clears both `_balance_cache` and `_accounts_cache` before each retry

### Related Issues

If you're still experiencing issues:
- See **Issue 2: Exchanges Underfunded** (above) for general funding guidance
- See **BROKER_CONNECTION_TROUBLESHOOTING.md** for connection issues
- Run `python3 diagnose_multi_broker_trading.py` for automated diagnosis
