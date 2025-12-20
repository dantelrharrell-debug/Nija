# NIJA Balance Debug Analysis

## Problem Summary
The bot shows **$0.00 balance** when starting, preventing trades from executing.

## Root Causes (in order of likelihood)

### 1. ❌ **MOST LIKELY: Funds in Consumer Wallet, Not Advanced Trade**
- **What you see:** "Move funds into your Advanced Trade portfolio"
- **Why:** The Coinbase API returns accounts marked as "CONSUMER" type
- **The bot's behavior:** Only counts accounts with `type == "ACCOUNT_TYPE_CRYPTO"` or platform containing "ADVANCED_TRADE"
- **Location in code:** [bot/broker_manager.py#L252](bot/broker_manager.py#L252)

```python
is_tradeable = account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform))
```

**Fix:** Transfer funds from "Coinbase" (consumer) to "Advanced Trade" Portfolio at:
https://www.coinbase.com/advanced-portfolio

---

### 2. ❌ **API Returns No Accounts (Zero Accounts)**
- **What you see:** Bot connects but balance is empty
- **Why:** API key might lack `accounts:read` permission
- **Check:** Run the [debug_balance.py](debug_balance.py) script to see how many accounts are returned

**Fix:** Edit API key permissions in Coinbase:
1. Go to API Keys Settings
2. Verify "View account details" is enabled
3. Regenerate key if needed

---

### 3. ❌ **Funds Are There But Account Type Filtering is Wrong**
- **What you see:** "Consumer USD: $X.XX" in logs but trading_balance = $0.00
- **Why:** Account type returned by API doesn't match expected "ACCOUNT_TYPE_CRYPTO"
- **Check:** Look for lines like:
  ```
  USD | avail=$X.XX | type=ACCOUNT_TYPE_??? | location=CONSUMER
  ```

**Fix:** Add more account type patterns to the is_tradeable check

---

## How to Debug

### Step 1: Run Balance Check Script
```bash
python /workspaces/Nija/debug_balance.py
```

This will:
- Check if API credentials are loaded
- Connect to Coinbase API
- List ALL accounts with their types
- Show which are tradeable vs consumer
- Calculate total available balance

### Step 2: Understand the Output

**Good scenario (funds available):**
```
[Account 1] USD
   Available: $100.00
   Type: ACCOUNT_TYPE_CRYPTO
   Status: ✅ TRADEABLE (Advanced Trade)

💰 TOTAL BALANCE: $100.00
```

**Bad scenario #1 (funds in wrong place):**
```
[Account 1] USD
   Available: $100.00
   Type: ???  (not ACCOUNT_TYPE_CRYPTO)
   Status: ❌ CONSUMER (Not for API trading)

💰 TOTAL BALANCE: $0.00
👉 DIAGNOSIS: Move funds to Advanced Trade portfolio
```

**Bad scenario #2 (no accounts):**
```
✅ Connection successful! Found 0 accounts
👉 DIAGNOSIS: API key lacks permission or no portfolio created
```

---

## Solution Checklist

- [ ] **Step 1:** Run `debug_balance.py` to see current state
- [ ] **Step 2:** Identify which scenario matches your situation
- [ ] **Step 3:** Take corrective action:
  - Scenario 1: Transfer funds via https://www.coinbase.com/advanced-portfolio
  - Scenario 2: Update API key permissions
  - Scenario 3: Contact Coinbase support (unusual case)
- [ ] **Step 4:** Re-run `debug_balance.py` to confirm fix
- [ ] **Step 5:** Restart bot - should see "✅ Sufficient capital" message

---

## Key Code Locations

| File | Line | Purpose |
|------|------|---------|
| [bot/broker_manager.py](bot/broker_manager.py#L228) | 228-300 | `get_account_balance()` - where balance is calculated |
| [bot/trading_strategy.py](bot/trading_strategy.py#L275) | 275-283 | `get_usd_balance()` - calls broker.get_account_balance() |
| [bot/trading_strategy.py](bot/trading_strategy.py#L135) | 135-175 | Balance check on startup - where $50 minimum is enforced |

---

## Environment Variables Needed

In your `.env` file (or Railway dashboard):
```
COINBASE_API_KEY=organizations/.../apiKeys/...
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----
```

**Note:** The script needs these to be loaded into the environment when the bot runs.

---

## Quick Reference: Account Type Meanings

| Type | Platform | Tradeable? | Purpose |
|------|----------|-----------|---------|
| `ACCOUNT_TYPE_CRYPTO` | ADVANCED_TRADE | ✅ Yes | Advanced Trade portfolio (for API trading) |
| `ACCOUNT_TYPE_FIAT` | (varies) | ❌ No | Regular Coinbase consumer wallet |
| `ACCOUNT_TYPE_VAULT` | (varies) | ❌ No | Vault (cold storage) |

---

## Next Steps

1. **Immediate:** Run `debug_balance.py` to see what's happening
2. **If $0 balance:** Transfer $100+ to Advanced Trade
3. **If still $0:** Check API key permissions
4. **If API shows funds elsewhere:** You may need Advanced Trade portfolio created first

The bot will automatically resume trading once:
- ✅ Balance ≥ $50
- ✅ Funds in Advanced Trade portfolio
- ✅ API credentials valid
