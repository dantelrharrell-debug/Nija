# API Key Access Issue - December 16, 2025

## Problem Summary

**What you see:** Funds in Advanced Trade on Coinbase app/website  
**What the API sees:** $0.00 in all accounts

## Root Cause

Your API key from **portal.cloud.coinbase.com** (Cloud Console) doesn't have access to your retail Coinbase account balances. Cloud Console API keys are for **institutional/developer accounts**, not retail accounts.

## Current API Status

✅ **Authentication:** Working (401 errors resolved)  
✅ **Connection:** Successful (can read 49 accounts, 2 portfolios)  
❌ **Balance Detection:** Shows $0.00 USD/USDC  
❌ **Trading:** Cannot execute (requires funds)

## Solution - Get the Correct API Key

### Option 1: Generate API Key from Coinbase App (RECOMMENDED)

1. **On your iPad, open Coinbase app**
2. Go to **Settings → Security → API Access**
3. Tap **"New API Key"** or **"Create API Key"**
4. Set permissions:
   - ✅ View (to see balances)
   - ✅ Trade (to execute orders)
5. **IMPORTANT:** Copy both:
   - API Key (starts with organizations/...)
   - Private Key (PEM format - multiple lines)
6. Save them securely and send to update `.env` file

### Option 2: Use Coinbase Advanced Trade API Keys

If Option 1 isn't available on iPad:

1. On iPad Safari, go to: **coinbase.com/settings/api**
2. Create API key with View + Trade permissions
3. This should give you access to retail account balances

## Alternative: Paper Trading Mode

If you can't resolve API access immediately, NIJA can run in **paper trading mode** for testing:

1. Set `PAPER_TRADING=true` in `.env`
2. Bot will simulate trades without real money
3. Test strategy logic and market scanning
4. Switch to live trading once API access is fixed

## Current Code Status

✅ **broker_manager.py:** Updated to accept all USD/USDC balances  
✅ **Balance detection:** Simplified, no platform filtering  
✅ **Authentication:** PEM key handling fixed  
✅ **Ready to trade:** Code is ready once API access is resolved

## Next Steps

1. **Generate correct API key** (from Coinbase app or website API settings)
2. **Update `.env` file** with new credentials
3. **Test balance detection:** Run `python scripts/print_accounts.py`
4. **Deploy NIJA:** Once balance shows correctly, bot will start trading

## Testing Commands

```bash
# Test new API credentials
python scripts/print_accounts.py

# Full diagnostic
python diagnose_balance.py

# Start NIJA bot (once balances show)
python main.py
```

## Contact Info

If you need help updating the `.env` file with new API credentials, just send:
- New API Key
- New Private Key (PEM format)

I'll update the configuration immediately.
