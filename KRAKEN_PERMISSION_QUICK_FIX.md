# Kraken "Permission Denied" Error - Quick Fix

**Problem**: Your bot logs show `EGeneral:Permission denied` when connecting to Kraken.

**Solution**: Your API key needs more permissions.

## Quick Fix Steps

1. Go to https://www.kraken.com/u/security/api
2. Edit your API key
3. Enable these 5 permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Save and restart the bot

**Security**: Do NOT enable "Withdraw Funds" permission

See [KRAKEN_PERMISSION_ERROR_FIX.md](KRAKEN_PERMISSION_ERROR_FIX.md) for detailed instructions.
