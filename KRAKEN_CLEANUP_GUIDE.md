# Kraken Account Cleanup Guide

## Overview

The `clean_kraken.py` script performs a complete cleanup of a Kraken trading account, preparing it for a fresh start. This is Step 1 of the restart process.

## What It Does

The script performs three main steps:

1. **Cancel All Open Orders** - Removes all pending orders from the Kraken order book
2. **Force-Sell All Positions** - Executes market sell orders for all cryptocurrency holdings
3. **Verify Cleanup** - Confirms that held in open orders = $0.00

### Features

- ✅ **Dry-Run Mode**: Preview actions without executing any trades
- ✅ **Dust Exclusion**: Automatically ignores positions below $1.00 USD value
- ✅ **Smart Symbol Conversion**: Handles various Kraken asset naming conventions
- ✅ **Rate Limiting**: Respects Kraken API rate limits to avoid errors
- ✅ **Comprehensive Error Handling**: Gracefully handles API failures
- ✅ **Clear Progress Output**: Shows detailed status of each action

## Prerequisites

### API Credentials

You must have Kraken API credentials set as environment variables:

```bash
# Option 1: Master credentials (preferred)
export KRAKEN_MASTER_API_KEY="your-api-key"
export KRAKEN_MASTER_API_SECRET="your-api-secret"

# Option 2: Legacy credentials (fallback)
export KRAKEN_API_KEY="your-api-key"
export KRAKEN_API_SECRET="your-api-secret"
```

### API Key Permissions

Your Kraken API key must have the following permissions enabled:

- ✅ **Query Funds** (required to check balance)
- ✅ **Query Open Orders & Trades** (required for position tracking)
- ✅ **Create & Modify Orders** (required to place sell orders)
- ✅ **Cancel/Close Orders** (required for order cancellation)

⚠️ **Security Note**: Do NOT enable "Withdraw Funds" permission - it's not needed and poses a security risk.

## Usage

### Dry-Run Mode (Recommended First)

Before executing the cleanup, run in dry-run mode to see what would be done:

```bash
python scripts/clean_kraken.py --dry-run
```

This will show:
- All open orders that would be cancelled
- All positions that would be sold
- Dust positions that would be ignored
- No actual trades will be executed

### Execute Cleanup

Once you've reviewed the dry-run output and are ready to proceed:

```bash
python scripts/clean_kraken.py
```

⚠️ **Warning**: This will execute REAL trades on your Kraken account. All positions will be sold at market prices. This action cannot be undone.

## Output Example

```
================================================================================
  KRAKEN ACCOUNT CLEANUP - Step 1
================================================================================

🔗 Connecting to Kraken...
✅ Connected to Kraken

💰 Current USD/USDT Balance: $1234.56

================================================================================
  STEP 1: Cancel All Open Orders
================================================================================

📋 Found 2 open order(s):
   • ETHUSD: buy 0.05000000 (limit) - ID: ABCD1234-EFGH...
   • BTCUSD: sell 0.01000000 (limit) - ID: WXYZ5678-IJKL...

🔴 Cancelling all orders...
   ✅ Cancelled: ETHUSD (ID: ABCD1234-EFGH...)
   ✅ Cancelled: BTCUSD (ID: WXYZ5678-IJKL...)

📊 Cancellation Summary: 2 succeeded, 0 failed

================================================================================
  STEP 2: Force-Sell All Positions
================================================================================

📋 Found 3 position(s) to sell:
   • ETH: 0.50000000 @ $2500.00 = $1250.00
   • BTC: 0.02000000 @ $45000.00 = $900.00
   • SOL: 10.00000000 @ $100.00 = $1000.00

🗑️  Found 1 dust position(s) (below $1.00) - will be ignored:
   • SHIB: 12345.00000000 = $0.12

🔴 Force-selling all positions...
   🔴 Selling ETH: 0.50000000 ($1250.00)...
      ✅ SOLD: ETH (Order ID: 1234567890...)
   🔴 Selling BTC: 0.02000000 ($900.00)...
      ✅ SOLD: BTC (Order ID: 0987654321...)
   🔴 Selling SOL: 10.00000000 ($1000.00)...
      ✅ SOLD: SOL (Order ID: 5678901234...)

📊 Sell Summary: 3 succeeded, 0 failed, 1 dust ignored

⏳ Waiting 5 seconds for orders to settle...

================================================================================
  STEP 3: Verify Cleanup
================================================================================

✅ Open orders: 0
✅ Only 1 dust position(s) remain (all < $1.00):
   • SHIB: 12345.00000000 = $0.12

================================================================================
  ✅ CLEANUP SUCCESSFUL - Held in open orders: $0.00
  (Dust positions below $1.00 are ignored)
================================================================================

💰 Final USD/USDT Balance: $4384.56

✅ Account is ready for restart with clean state
```

## What Happens to Dust?

**Dust positions** are cryptocurrency holdings with a total USD value below $1.00. These are:

- ✅ **Automatically excluded** from selling
- ✅ **Ignored in position counting**
- ✅ **Safe to leave in account**

Why? Kraken has a minimum order cost of $10.00. Attempting to sell dust would fail and waste API calls.

## Edge Cases & Troubleshooting

### Positions Too Small to Sell

Some positions may be above the dust threshold ($1.00) but below Kraken's minimum order cost ($10.00):

```
⚠️  Skipping XRP: $5.23 < $10.00 minimum
    This position is too small to sell on Kraken (will remain as dust)
```

These positions cannot be sold on Kraken due to exchange minimums. They will remain in your account but won't affect trading.

### API Permission Errors

If you see permission errors:

```
❌ Kraken connection test failed: EGeneral:Permission denied
```

Fix:
1. Go to https://www.kraken.com/u/security/api
2. Edit your API key permissions
3. Enable all required permissions (see Prerequisites above)
4. Save and retry

### Rate Limit Errors

The script includes built-in rate limiting:
- 0.1 second delay between order cancellations
- 0.2 second delay between sell orders

If you still hit rate limits, the script will show the error. Wait a few minutes and retry.

### Price Lookup Failures

If the script cannot determine a price for an asset:

```
⚠️  Could not get price for XYZ (asset: XYZ): [error]
⚠️  Skipping XYZ: cannot verify dust threshold without price
```

This is safe - the script will skip assets it cannot price to avoid errors.

## Safety Features

The script includes multiple safety checks:

1. **Dry-run mode** - Test before executing
2. **Dust exclusion** - Won't attempt to sell unprofitable positions
3. **Minimum validation** - Respects Kraken's $10.00 minimum order cost
4. **Error handling** - Continues on individual failures
5. **Rate limiting** - Avoids API throttling
6. **Verification step** - Confirms cleanup success

## After Cleanup

Once cleanup is successful:

1. ✅ All open orders are cancelled
2. ✅ All significant positions are sold
3. ✅ Account shows $0.00 held in open orders
4. ✅ USD/USDT balance reflects proceeds from sales
5. ✅ Ready to restart bot with clean state

You can now proceed to **Step 3: Restart with clean state** as outlined in your restart guide.

## Support

If you encounter issues:

1. Run with `--dry-run` first to identify problems
2. Check API credentials and permissions
3. Verify network connectivity to Kraken
4. Review error messages for specific failures
5. Check Kraken's status page for exchange issues

## Technical Details

- **Language**: Python 3.11+
- **Dependencies**: krakenex, pykrakenapi (in requirements.txt)
- **Rate Limits**: 15 requests/second (private endpoints)
- **Dust Threshold**: $1.00 USD
- **Minimum Order**: $10.00 USD (Kraken limit)

---

**Created**: 2026-01-23
**Version**: 1.0
**Part of**: NIJA Trading Bot - Kraken Integration
