# Coinbase Portfolio Fix - INSUFFICIENT_FUND Error

## Problem

Your bot is connected to Coinbase API (live mode) but all trades fail with:
```
INSUFFICIENT_FUND: Insufficient balance in source account
```

## Root Cause

Your **$57 USD is in the wrong Coinbase wallet**:
- ❌ Consumer/Retail Wallet (cannot trade from this)
- ✅ Advanced Trade Portfolio (need funds here)

Coinbase has **two separate wallets**:
1. **Consumer Wallet** - For buying/selling on Coinbase.com
2. **Advanced Trade Portfolio** - For API trading

Your API keys can see both, but can only TRADE from the Advanced Trade portfolio.

## Solution: Move USD to Advanced Trade Portfolio

### Step 1: Go to Coinbase Advanced Trade
https://advanced.coinbase.com

### Step 2: Check Your Portfolios
1. Click your **profile icon** (top right)
2. Select **"Portfolios"**
3. Look for **"Default"** or **"Trading"** portfolio
4. Check if USD balance shows $0.00

### Step 3: Transfer Funds
1. Click **"Deposit"** button
2. Select **"From Coinbase"** (transfer from Consumer wallet)
3. Choose **"USD"**
4. Enter **$57.00**
5. Select destination: **"Default"** portfolio
6. Confirm transfer

### Step 4: Verify Transfer
After transfer completes:
1. Advanced Trade portfolio should show **$57.00 USD**
2. Consumer wallet should show **$0.00 USD**

### Step 5: Redeploy Bot on Render
1. Go to Render dashboard
2. Click **"Manual Deploy"**
3. Wait for deployment to complete
4. Check new logs for:
   ```
   💰 TOTAL BALANCE:
      USD:  $57.00
      USDC: $0.00
      TRADING BALANCE: $57.00
   ```

## Expected Behavior After Fix

### Before (Current):
```
❌ Trade failed for XLM-USD:
   Status: unfilled
   Error: Unknown error from broker
   Full order response: {'error': 'INSUFFICIENT_FUND', ...}
```

### After (Fixed):
```
✅ Trade executed: XLM-USD BUY
   Entry: $0.206
   Stop Loss: $0.202 (-2.0%)
   Take Profit: $0.218 (+6.0%)
```

## Quick Verification

Run this check after transferring funds:
1. Open Render logs
2. Look for startup message:
   ```
   💰 TOTAL BALANCE:
      TRADING BALANCE: $57.00  ← Should see your real balance
   ```
3. If still shows $0.00, wait 1-2 minutes and redeploy again

## Still Having Issues?

If trades still fail after transfer:
1. Verify transfer completed in Coinbase Advanced Trade
2. Check that API keys have "Trade" permission enabled
3. Ensure you're looking at "Advanced Trade" not "Coinbase.com"

## Technical Details

The bot uses Coinbase Advanced Trade API which requires:
- Funds in **Advanced Trade portfolio** (not Consumer wallet)
- API keys with "Trade" permission
- Minimum $5.00 USD per trade
