# Kraken Cleanup Quick Reference

## Quick Start

```bash
# Step 1: Preview what will be cleaned (recommended)
python scripts/clean_kraken.py --dry-run

# Step 2: Execute cleanup
python scripts/clean_kraken.py
```

## What It Does

1. Cancels ALL open orders on Kraken
2. Force-sells ALL crypto positions above $10 (market orders)
3. Sweeps dust – converts residual balances (below $10) to USD via ConvertFunds, with a market-order fallback
4. Verifies: Held in open orders = $0.00

## Requirements

Set environment variables:
```bash
export KRAKEN_PLATFORM_API_KEY="your-key"
export KRAKEN_PLATFORM_API_SECRET="your-secret"
```

API Permissions needed:
- Query Funds
- Query Open Orders & Trades
- Create & Modify Orders
- Cancel/Close Orders

## Full Documentation

See [KRAKEN_CLEANUP_GUIDE.md](/KRAKEN_CLEANUP_GUIDE.md) for complete documentation.

## Safety

- ✅ Includes dry-run mode
- ✅ Sweeps dust via ConvertFunds (no minimum required)
- ✅ Respects Kraken minimums for regular market orders
- ✅ Rate-limited API calls
- ✅ Comprehensive error handling
