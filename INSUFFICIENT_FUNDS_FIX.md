# Insufficient Funds Fix - December 19, 2025

## Problem

Your trading bot was showing `$25.81` available balance but ALL trades were failing with `INSUFFICIENT_FUND` error from Coinbase API.

## Root Cause

The `get_account_balance()` method was **adding balances from both Consumer wallet and Advanced Trade portfolio**, but Coinbase Advanced Trade API can **ONLY execute trades from the Advanced Trade portfolio**.

This created a mismatch:
- Bot calculated: Consumer balance ($X) + Advanced Trade balance ($Y) = $25.81
- Coinbase saw: Advanced Trade balance only = likely $0 or < $5

## The Fix

Modified [bot/broker_manager.py](bot/broker_manager.py) `get_account_balance()` method to:

1. **Still check Consumer wallet** - but only for diagnostic logging (marked as "NOT TRADABLE")
2. **Only return Advanced Trade balance** - this is the actual tradable amount
3. **Enhanced logging** - clearly shows which balance is tradable vs not tradable
4. **Better error messages** - if funds are in wrong place, tells user exactly how to fix it

### Key Changes

```python
# OLD (WRONG): Added both Consumer + Advanced Trade
usd_balance += consumer_balance  # ❌ This can't be used for trading!
usd_balance += advanced_trade_balance

# NEW (CORRECT): Only use Advanced Trade
consumer_usd = consumer_balance  # Tracked separately
usd_balance = advanced_trade_balance  # Only this is tradable
```

## What You Need To Do

Run the diagnostic script to see where your funds actually are:

```bash
python check_balance_location.py
```

This will show you:
- How much is in Consumer wallet (NOT tradable via API)
- How much is in Advanced Trade portfolio (TRADABLE)
- Total tradable balance

### If Funds Are In Consumer Wallet

You need to transfer them to Advanced Trade:

1. Go to: https://www.coinbase.com/advanced-portfolio
2. Click **"Deposit"** → **"From Coinbase"**
3. Transfer your USD/USDC to Advanced Trade portfolio
4. Transfer is **INSTANT** - bot will work immediately after

### If No Funds Anywhere

You need to deposit funds to Coinbase first, then transfer to Advanced Trade.

## Why This Happened

Coinbase has two separate account systems:

| Account Type | API | Can Trade Via Bot? |
|-------------|-----|-------------------|
| **Consumer Wallet** | v2 API (legacy) | ❌ NO - Retail only |
| **Advanced Trade Portfolio** | v3 API (current) | ✅ YES - API trading |

The bot uses the Advanced Trade v3 API for trading, which can ONLY access funds in the Advanced Trade portfolio. Consumer wallet funds are completely separate and cannot be used for API trading.

## Testing

After deploying this fix:

1. Run `python check_balance_location.py` to verify balance location
2. Transfer funds to Advanced Trade if needed
3. Bot will now show accurate tradable balance
4. Pre-flight checks will prevent orders if Advanced Trade balance is insufficient

## Expected Behavior Now

### Good Balance (Sufficient Advanced Trade Funds)
```
💰 BALANCE SUMMARY:
   Consumer USD (NOT TRADABLE):  $0.00
   Consumer USDC (NOT TRADABLE): $0.00
   Advanced Trade USD:  $25.81 [TRADABLE]
   Advanced Trade USDC: $0.00 [TRADABLE]
   ▶ TRADING BALANCE: $25.81
   ✅ Sufficient funds in Advanced Trade for trading!
```

### Problem (Funds in Wrong Place)
```
💰 BALANCE SUMMARY:
   Consumer USD (NOT TRADABLE):  $25.81
   Consumer USDC (NOT TRADABLE): $0.00
   Advanced Trade USD:  $0.00 [TRADABLE]
   Advanced Trade USDC: $0.00 [TRADABLE]
   ▶ TRADING BALANCE: $0.00
   
🚨 INSUFFICIENT TRADING BALANCE IN ADVANCED TRADE!
   🔍 PROBLEM FOUND: Your funds are in Consumer wallet!
   Consumer wallet has $25.81 but it CANNOT be used for API trading
   
   HOW TO FIX - Transfer to Advanced Trade:
   1. Go to: https://www.coinbase.com/advanced-portfolio
   2. Click 'Deposit' → 'From Coinbase'
   3. Transfer your USD/USDC to Advanced Trade portfolio
   4. The transfer is INSTANT (no waiting)
```

## Files Modified

- [bot/broker_manager.py](bot/broker_manager.py) - Fixed `get_account_balance()` method
- [check_balance_location.py](check_balance_location.py) - New diagnostic script (created)

## Related Documentation

- [COINBASE_SETUP.md](COINBASE_SETUP.md)
- [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md)
- [COINBASE_COMPLETE.md](COINBASE_COMPLETE.md)
