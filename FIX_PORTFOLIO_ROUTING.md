# 🔧 Portfolio Routing Fix

## The Problem

You have $17.54 in a portfolio named "NIJA", but Coinbase Advanced Trade API trades execute from the **default trading portfolio** which has $0.

The bot can READ from the NIJA portfolio but can't TRADE from it because the Coinbase Python SDK (`coinbase-advanced-py`) doesn't support the `portfolio_uuid` parameter in `market_order_buy()`.

## The Solution

**Transfer funds from "NIJA" portfolio to your default trading portfolio:**

### Option 1: Via Coinbase Website (Easiest)

1. Go to: https://www.coinbase.com/advanced-trade/trade
2. Click on your account/portfolio dropdown (top right)
3. Select "Portfolios" or "Manage portfolios"
4. Find your "NIJA" portfolio with $17.54
5. Transfer the funds → Default portfolio
6. Done! Both Render and Railway will immediately start trading

### Option 2: Via Coinbase Mobile App

1. Open Coinbase app
2. Tap profile → Portfolios
3. Select "NIJA" portfolio
4. Tap "Transfer"
5. Move to Default portfolio
6. Done!

## What the Code Update Does

The code changes I just made will:
1. ✅ Auto-detect your NIJA portfolio
2. ✅ Log which portfolio has funds
3. ✅ Show portfolio UUID in logs
4. ⚠️ **BUT still can't route trades to it** (SDK limitation)

## After You Transfer Funds

Once you move the $17.54 to the default portfolio:
- Both Render and Railway deployments will see it
- Trades will execute successfully
- You'll see "Order filled successfully" instead of "INSUFFICIENT_FUND"

## Want to Verify Your Portfolios?

Run this locally:
```bash
python check_balance_location.py
```

It will show all portfolios and where your funds are.

## Technical Details (for nerds 🤓)

The Coinbase Advanced Trade v3 API endpoint for creating orders is:
```
POST /api/v3/brokerage/orders
```

This endpoint DOES support a `portfolio_uuid` parameter in the JSON body, but the Python SDK's `market_order_buy()` wrapper function doesn't expose it.

To truly route trades, we would need to:
1. Use raw API calls instead of SDK methods
2. Manually construct JWT tokens
3. Handle all request signing

That's a bigger rewrite. **Much easier to just transfer the funds!**
