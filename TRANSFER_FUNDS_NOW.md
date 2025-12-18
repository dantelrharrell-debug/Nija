# 🚨 YOUR FUNDS ARE IN THE WRONG ACCOUNT

## Problem
Your bot keeps getting `INSUFFICIENT_FUND` errors even though you have money in Coinbase.

**Reason:** Your funds are in a **Consumer/Retail wallet** (type='wallet'), which **CANNOT** be used for trading via API.

## Solution: Transfer to Advanced Trade (Takes 2 minutes)

### Step 1: Log into Advanced Trade
Go to: **https://www.coinbase.com/advanced-portfolio**

### Step 2: Transfer Funds
1. Click the **"Deposit"** button (top right)
2. Select **"From Coinbase"** (this transfers from your Consumer wallet)
3. Choose **USD** or **USDC**
4. Enter the amount you want to trade with
5. Click **"Deposit"**

### Step 3: Verify
After transfer:
- Your Advanced Trade portfolio will show the balance
- The bot will detect it immediately (no code changes needed)
- Trades will execute successfully

## Why This Happens

Coinbase has **two separate systems**:

| Account Type | Can Use for Bot Trading? | How to Check |
|-------------|-------------------------|--------------|
| **Consumer Wallet** | ❌ NO | Coinbase.com main page |
| **Advanced Trade** | ✅ YES | advanced.coinbase.com |

The API can *see* both accounts but can only *trade* from Advanced Trade.

## Quick Check

Run this to see your current accounts:
```bash
python check_my_account.py
```

Look for lines like:
- `⚠️ Skipping USD: $XX.XX (Consumer account, not tradable)`

That's your money stuck in the wrong place!

## After Transfer

Once you move funds to Advanced Trade, you should see:
```
✅ USD: $XX.XX (type=ACCOUNT_TYPE_CRYPTO)
```

And the bot will start trading automatically.

---

**Need help?** The error logs will show exactly which accounts have funds and which are skipped.
