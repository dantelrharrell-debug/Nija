# Quick Fix: Enable Multi-Broker Trading

## Problem
Your logs show all exchanges are connected, but only Coinbase Master is trading:
```
✅ Coinbase | ✅ Kraken (Master) | ✅ OKX | ❌ Binance | ❌ Alpaca
```

## Most Likely Cause

**Independent multi-broker trading mode is NOT enabled.**

The bot defaults to single-broker mode if `MULTI_BROKER_INDEPENDENT` is not explicitly set to `true`.

## Quick Fix (90% of cases)

### Option 1: Railway Platform

1. Go to your Railway dashboard
2. Click on your NIJA service
3. Click "Variables" tab
4. Click "+ New Variable"
5. Add:
   - **Name:** `MULTI_BROKER_INDEPENDENT`
   - **Value:** `true`
6. Railway will automatically restart the deployment
7. Wait 2-3 minutes for bot to start
8. Check logs for: `🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE`

### Option 2: Render Platform

1. Go to your Render dashboard
2. Click on your NIJA service
3. Click "Environment" tab
4. Click "Add Environment Variable"
5. Add:
   - **Key:** `MULTI_BROKER_INDEPENDENT`
   - **Value:** `true`
6. Click "Save Changes"
7. Click "Manual Deploy" → "Deploy latest commit"
8. Wait 2-3 minutes for bot to start
9. Check logs for: `🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE`

### Option 3: Local .env File

```bash
echo "MULTI_BROKER_INDEPENDENT=true" >> .env
./start.sh
```

## Verification

After adding the environment variable and restarting, check your logs for:

```
🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE
═══════════════════════════════════════════════════════════════
Each broker will trade independently in isolated threads.
Failures in one broker will NOT affect other brokers.
═══════════════════════════════════════════════════════════════

🔍 Detecting funded brokers...
   💰 coinbase: $XX.XX
      ✅ FUNDED - Ready to trade
   💰 kraken: $XX.XX
      ✅ FUNDED - Ready to trade
   💰 okx: $XX.XX
      ✅ FUNDED - Ready to trade

✅ Started independent trading thread for coinbase (MASTER)
✅ Started independent trading thread for kraken (MASTER)
✅ Started independent trading thread for okx (MASTER)
```

You should then see cycle messages for ALL exchanges:
```
🔄 coinbase - Cycle #1
🔄 kraken - Cycle #1
🔄 okx - Cycle #1
```

## If That Doesn't Fix It

Run the diagnostic script to identify the exact issue:

```bash
python3 diagnose_multi_broker_trading.py
```

This will check:
- ✅ Whether env var is set correctly
- ✅ Which exchanges have sufficient funds (≥ $1.00)
- ✅ Connection status for each exchange
- ✅ Whether trading threads are starting
- ✅ Specific error messages for any failures

Then follow the specific recommendations in the output.

## Other Possible Issues

If `MULTI_BROKER_INDEPENDENT=true` is already set, the issue might be:

### 1. Exchanges Not Funded
- **Symptom:** Exchanges connect but threads don't start
- **Fix:** Fund each exchange account with at least $1.00 ($25+ recommended)
- **Check:** Run `python3 diagnose_multi_broker_trading.py`

### 2. API Permission Errors (Kraken)
- **Symptom:** Kraken shows "Permission denied" in logs
- **Fix:** See `KRAKEN_PERMISSION_ERROR_FIX.md`
- **Quick fix:** Go to https://www.kraken.com/u/security/api and enable:
  - Query Funds
  - Create & Modify Orders
  - Query Open Orders & Trades
  - Cancel/Close Orders

### 3. Invalid Credentials (OKX)
- **Symptom:** OKX shows "Invalid passphrase" or "API key doesn't exist"
- **Fix:** Verify credentials at https://www.okx.com/account/my-api
- **Common error:** Using placeholder value like "your_passphrase"

## Summary

**90% of cases:** Just add `MULTI_BROKER_INDEPENDENT=true` to environment variables and restart.

**10% of cases:** Run diagnostic script to identify specific issue:
```bash
python3 diagnose_multi_broker_trading.py
```

---

For detailed troubleshooting, see: `TROUBLESHOOTING_MULTI_BROKER_TRADING.md`
