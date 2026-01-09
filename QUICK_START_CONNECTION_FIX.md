# Quick Start: Broker Connection Fixes

## What Was Fixed

Your trading bot was experiencing connection issues. We've implemented comprehensive fixes:

### 1. Better Recovery from 403 Errors
- **Before**: 6 retry attempts with 10s base delay
- **After**: 10 retry attempts with 15s base delay (capped at 120s)
- **Result**: Bot has more chances to recover from temporary API blocks

### 2. Clearer Error Messages
- **Coinbase**: Shows retry progress and remaining attempts
- **Kraken**: Shows exact environment variable names to set
- **Alpaca**: Detects and explains paper trading issues
- **Result**: You know exactly what to fix

### 3. Diagnostic Tools
- **test_connection_fixes.py**: Verifies fixes work correctly
- **diagnose_broker_status.py**: Helps troubleshoot connection issues
- **Result**: Easy self-service troubleshooting

## How to Use

### Check Your Current Status

Run the diagnostic tool to see which brokers are configured and connected:

```bash
python3 diagnose_broker_status.py
```

This will:
1. Show which credentials are configured
2. Test connections to each broker
3. Provide specific recommendations for fixing issues

### Fix Missing Credentials

If the diagnostic tool shows missing credentials, set them:

**For Coinbase (required)**:
```bash
export COINBASE_API_KEY='your-api-key'
export COINBASE_API_SECRET='your-api-secret'
```

**For Kraken (optional)**:
```bash
export KRAKEN_MASTER_API_KEY='your-api-key'
export KRAKEN_MASTER_API_SECRET='your-api-secret'
```

**For Alpaca (optional, for stock trading)**:
```bash
export ALPACA_API_KEY='your-api-key'
export ALPACA_API_SECRET='your-api-secret'
export ALPACA_PAPER='true'  # or 'false' for live trading
```

### Start the Bot

After setting credentials, start the bot normally:

```bash
./start.sh
```

or

```bash
python3 bot.py
```

## What to Expect

### Successful Connection
```
⏱️  Waiting 30s before connecting to avoid rate limits...
✅ Startup delay complete, beginning broker connections...
📊 Attempting to connect Coinbase Advanced Trade...
✅ Connected to Coinbase Advanced Trade API
✅ CONNECTED BROKERS: Coinbase
💰 TOTAL BALANCE ACROSS ALL BROKERS: $57.42
```

### Recovery from 403 Errors
```
📊 Attempting to connect Coinbase Advanced Trade...
⚠️  Connection attempt 1/10 failed (retryable): 403 Client Error: Forbidden Too many errors
🔄 Retrying connection in 15.0s (attempt 2/10)...
⚠️  Connection attempt 2/10 failed (retryable): 403 Client Error: Forbidden Too many errors
🔄 Retrying connection in 30.0s (attempt 3/10)...
✅ Connected to Coinbase Advanced Trade API (succeeded on attempt 3)
```

### Missing Credentials
```
⚠️  Kraken credentials not configured for MASTER (skipping)
   To enable Kraken MASTER trading, set:
      KRAKEN_MASTER_API_KEY=<your-api-key>
      KRAKEN_MASTER_API_SECRET=<your-api-secret>
```

## Troubleshooting

### Bot Still Can't Connect?

1. **Wait 5-10 minutes**: API rate limits reset over time
2. **Check credentials**: Make sure they're from Coinbase Advanced Trade (not Coinbase Pro)
3. **Verify API permissions**: Key needs 'view' and 'trade' permissions
4. **Run diagnostics**: `python3 diagnose_broker_status.py`

### Still Having Issues?

1. Check the logs for specific error messages
2. Review `BROKER_CONNECTION_FIX_JAN_2026.md` for detailed documentation
3. Run `python3 test_connection_fixes.py` to verify fixes are working

## Key Improvements

✅ **10 retry attempts** (vs 6 previously)  
✅ **Longer delays** between retries (15s base)  
✅ **120s cap** prevents excessive waits  
✅ **Clear error messages** show exactly what to fix  
✅ **Diagnostic tool** for easy troubleshooting  
✅ **All tests passing** - verified and ready  

## Questions?

- **Full documentation**: See `BROKER_CONNECTION_FIX_JAN_2026.md`
- **Diagnostic tool**: Run `python3 diagnose_broker_status.py`
- **Test suite**: Run `python3 test_connection_fixes.py`

---

**Status**: ✅ All fixes implemented and tested  
**Date**: January 9, 2026  
**Branch**: copilot/fix-connection-issues
