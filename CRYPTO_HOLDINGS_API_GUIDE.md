# Coinbase API - How to Access Crypto Holdings

## ⚠️ CRITICAL: Two Different APIs, Two Different Views

### The Problem
Coinbase has **TWO ways** to query account data, and they return **DIFFERENT results**:

1. **`get_accounts()` API** - Returns account list but shows `Available: 0.0` for all crypto
2. **`get_portfolio_breakdown()` API** - Returns actual crypto holdings with real balances

### The Solution
**ALWAYS use `get_portfolio_breakdown()` to see crypto holdings!**

---

## Working Code Pattern

### ❌ WRONG WAY (shows zero balances):
```python
accounts_response = broker.client.get_accounts()
all_accounts = accounts_response.accounts

for account in all_accounts:
    currency = account.currency
    available = float(account.available_balance.value)
    # PROBLEM: available will be 0.0 for all crypto!
```

### ✅ CORRECT WAY (shows real balances):
```python
# Use the broker's get_account_balance() method
balance_info = broker.get_account_balance()
crypto_holdings = balance_info.get('crypto', {})

for currency, quantity in crypto_holdings.items():
    if quantity > 0.00000001:
        # This will show actual holdings!
        print(f"{currency}: {quantity}")
```

---

## Behind the Scenes

The `broker.get_account_balance()` method uses this flow:

1. Calls `client.get_portfolios()` to get portfolio list
2. Finds the DEFAULT portfolio
3. Calls `client.get_portfolio_breakdown(portfolio_uuid)`
4. Iterates through `breakdown.spot_positions`
5. Returns crypto holdings as dictionary: `{'BTC': 0.000332, 'ETH': 0.016627, ...}`

---

## Real Example from December 22, 2025

**What `get_accounts()` showed:**
- All 49 accounts: `Available: 0.0`
- Looked like no crypto holdings at all

**What `get_portfolio_breakdown()` showed:**
- ETH: 0.016627 (worth $50.07)
- BTC: 0.000332 (worth $29.62)
- SOL: 0.156029 (worth $19.72)
- XRP: 5.129064 (worth $9.88)
- ATOM: 0.305094 (worth $0.60)
- **Total: $110.60 in crypto!**

---

## Why This Matters

If you try to sell crypto using `get_accounts()`:
- ❌ Script will say "No crypto to sell"
- ❌ Won't find any positions
- ❌ Account will keep bleeding

If you use `get_portfolio_breakdown()`:
- ✅ Sees all crypto holdings
- ✅ Can sell positions properly
- ✅ Can recover capital

---

## Quick Reference

### To check balances:
```bash
python3 check_crypto_value.py
```

### To sell all crypto:
```bash
python3 auto_sell_all_crypto.py
```

Both scripts now use `get_portfolio_breakdown()` internally.

---

## Files That Use Correct Method

✅ `bot/broker_manager.py` - `get_account_balance()` method (lines 400-550)  
✅ `auto_sell_all_crypto.py` - Uses `broker.get_account_balance()`  
✅ `check_crypto_value.py` - Uses `broker.get_account_balance()`  
❌ `debug_accounts.py` - Uses `get_accounts()` (for debugging only, not for trading)

---

## REMEMBER THIS

**Coinbase Advanced Trade API has TWO truth sources:**
- `get_accounts()` = ❌ Shows ZERO for crypto (unreliable)
- `get_portfolio_breakdown()` = ✅ Shows REAL crypto holdings (use this!)

**Always use the portfolio breakdown method!**
