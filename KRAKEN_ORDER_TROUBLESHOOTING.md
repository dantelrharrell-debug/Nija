# Kraken Order Troubleshooting Guide

## 🚨 Common Kraken Order Failures and How to Fix Them

This guide helps you diagnose and fix Kraken order failures in NIJA.

---

## 📋 Table of Contents

1. [Order Validation Failures](#order-validation-failures)
2. [Symbol Format Errors](#symbol-format-errors)
3. [Minimum Size Violations](#minimum-size-violations)
4. [API Connection Issues](#api-connection-issues)
5. [txid Confirmation Failures](#txid-confirmation-failures)
6. [Balance and Tier Issues](#balance-and-tier-issues)

---

## 1. Order Validation Failures

### Error Message:
```
❌ ORDER VALIDATION FAILED [kraken] ETH-USD
   Reason: Order size $5.00 below Kraken minimum $10.00
```

### What It Means:
Kraken requires a minimum $10 USD value per trade. Your order was rejected before being sent to Kraken.

### Solutions:
1. ✅ **Increase position size** to $10 or higher
2. ✅ **Wait for stronger signals** that warrant larger positions
3. ✅ **Check your tier** - ensure you're INVESTOR+ ($100+ balance)

### Why This Happens:
Kraken's minimum exists to prevent spam and ensure orders are economically viable.

---

## 2. Symbol Format Errors

### Error Message:
```
❌ ORDER VALIDATION FAILED [kraken] SHIB-BUSD
   Reason: Kraken only supports USD/USDT pairs. Symbol 'SHIB-BUSD' is not supported.
```

### What It Means:
Kraken **only** supports pairs that end in:
- `/USD` or `-USD`
- `/USDT` or `-USDT`

**Not supported:**
- BUSD pairs (Kraken doesn't have BUSD)
- EUR pairs (not implemented in NIJA)
- Exotic stablecoins

### Solutions:
1. ✅ **Skip unsupported pairs** - NIJA will automatically skip them
2. ✅ **Use Coinbase** for BUSD pairs (if configured)
3. ✅ **Stick to USD/USDT** pairs on Kraken

### Automatic Conversions:
NIJA automatically converts symbols for Kraken:
- `BTC-USD` → `XBTUSD` (BTC becomes XBT on Kraken)
- `ETH/USDT` → `ETHUSDT`
- `SOL-USD` → `SOLUSD`

---

## 3. Minimum Size Violations

### Error Message:
```
❌ ORDER VALIDATION FAILED [kraken] BTC-USD
   Reason: [INVESTOR Tier] Trade size $8.00 below tier minimum $10.00
   Account balance: $150.00
```

### What It Means:
You have two minimums to satisfy:
1. **Kraken minimum**: $10
2. **Tier minimum**: Varies by balance

Your trade was below the tier minimum for your account balance.

### Tier Minimums:
| Balance | Tier | Minimum Trade |
|---------|------|---------------|
| $100–$249 | SAVER | $15 |
| $250–$999 | INVESTOR | $20 |
| $1k–$4.9k | INCOME | $30 |
| $5k–$24.9k | LIVABLE | $50 |
| $25k+ | BALLER | $100 |

### Solutions:
1. ✅ **Deposit more** to reach next tier (more flexibility)
2. ✅ **Wait for larger signals** that meet your tier minimum
3. ✅ **Trust the system** - blocked trades protect you from fees

### Why This Helps:
Tier minimums ensure trades are large enough to be profitable after fees:
- **Kraken fees**: 0.52% round-trip
- **$10 trade**: $0.05 in fees (need 0.5%+ profit to overcome)
- **$2 trade**: $0.01 in fees (need 0.5%+ profit, but very tight)

---

## 4. API Connection Issues

### Error Message:
```
❌ Kraken API not connected
```

### What It Means:
NIJA cannot reach Kraken's API or credentials are invalid.

### Solutions:

#### Check 1: Verify Credentials
```bash
# Check environment variables
echo $KRAKEN_API_KEY
echo $KRAKEN_API_SECRET
```

Make sure:
- ✅ API key starts with your username
- ✅ API secret is 88 characters (base64 encoded)
- ✅ Both are in your `.env` file

#### Check 2: API Key Permissions
Go to https://www.kraken.com/u/security/api and verify your API key has:
- ✅ **Query Funds** (check balance)
- ✅ **Query Open Orders & Trades** (track positions)
- ✅ **Query Closed Orders & Trades** (history)
- ✅ **Create & Modify Orders** (place trades)
- ✅ **Cancel/Close Orders** (stop losses)

**Do NOT enable:**
- ❌ Withdraw Funds (security risk)

#### Check 3: Network Connection
```bash
# Test Kraken API connectivity
curl https://api.kraken.com/0/public/Time
```

Should return:
```json
{"error":[],"result":{"unixtime":1234567890,"rfc1123":"..."}}
```

### Permission Error Example:
```
❌ Kraken connection test failed: EGeneral:Permission denied
   ⚠️  API KEY PERMISSION ERROR
   Your Kraken API key does not have the required permissions.
```

**Fix:** Enable all required permissions at https://www.kraken.com/u/security/api

---

## 5. txid Confirmation Failures

### Error Message:
```
⚠️  ORDER NOT FULLY FILLED:
   • Order ID: O3G7XK-XXXXX-XXXXXX
   • Status: pending (expected 'closed')
   • Filled Volume: 0 (expected > 0)
```

### What It Means:
Order was placed but didn't fill immediately. Could be:
- Slow market conditions
- Partial fill
- Order stuck in queue

### What NIJA Does:
1. Marks order as `pending` (not `filled`)
2. Logs warning for manual verification
3. Continues operation (doesn't crash)

### Solutions:

#### Check 1: Verify in Kraken UI
1. Go to https://www.kraken.com
2. Navigate to **Portfolio → Trade History**
3. Look for order ID
4. Check status:
   - ✅ `closed` = filled
   - ⏳ `pending` = still processing
   - ❌ `canceled` = rejected

#### Check 2: Wait and Re-Query
Sometimes orders take 1-2 seconds to fill. NIJA waits 0.5 seconds by default.

For slower fills:
- Order will eventually show in Trade History
- NIJA logs it as `pending` to be safe
- No action needed unless order is stuck >1 minute

#### Check 3: Balance Impact
```bash
# Check if balance changed (order filled even if verification failed)
# If balance decreased (buy) or increased (sell), order likely filled
```

### Why This Happens:
- Kraken API returns txid immediately
- Order fill can take 100-1000ms
- NIJA verification runs after 500ms
- Some orders fill slower (low liquidity pairs)

---

## 6. Balance and Tier Issues

### Error Message:
```
❌ ORDER VALIDATION FAILED [kraken] SOL-USD
   Reason: Account balance $15.00 below minimum tier requirement $25.00
   Cannot execute trades.
```

### What It Means:
Your Kraken balance is below **$100**, the absolute minimum for NIJA trading.

### Solutions:

#### Option 1: Deposit More (Recommended)
Deposit at least:
- **$100** → SAVER tier (minimum to trade)
- **$250** → INVESTOR tier (consistent participation) ⭐
- **$1,000** → INCOME tier (serious retail trading)

#### Option 2: Transfer from Another Exchange
If you have funds on Coinbase:
1. Withdraw USDT/USD to Kraken
2. Wait for confirmation (5-30 minutes)
3. Restart NIJA to detect new balance

#### Option 3: Combine Accounts
Use NIJA's multi-account feature to pool liquidity.

### Why $25 Minimum?
- Kraken minimum: $10 per trade
- Need buffer for 2+ trades
- Below $25, portfolio management becomes impractical
- Fees destroy profits on micro-accounts

---

## 🔍 Advanced Diagnostics

### Enable Debug Logging

Add to your `.env`:
```bash
LOG_LEVEL=DEBUG
```

This shows:
- Every validation step
- Symbol conversions
- API call details
- Full error traces

### Check Logs for Full Details

Look for:
```
📝 Placing Kraken market buy order: ETHUSD
   Size: 0.015 base, Validation: PASSED
```

vs

```
❌ ORDER VALIDATION FAILED [kraken] ETH-USD
   Reason: [INVESTOR Tier] Trade size $8.00 below tier minimum $10.00
```

### Manual Order Test

Test Kraken API manually:
```python
import krakenex
from pykrakenapi import KrakenAPI

api = krakenex.API(key='YOUR_KEY', secret='YOUR_SECRET')
k = KrakenAPI(api)

# Test balance
balance = api.query_private('Balance')
print(balance)

# Test order (0.001 BTC)
order = api.query_private('AddOrder', {
    'pair': 'XBTUSD',
    'type': 'buy',
    'ordertype': 'market',
    'volume': '0.001'
})
print(order)
```

---

## 📞 Still Having Issues?

### Before Asking for Help

Collect this information:
1. **Full error message** from logs
2. **Account balance** on Kraken
3. **Symbol** you're trying to trade
4. **Order size** attempted
5. **Tier** detected (from logs)
6. **API permissions** screenshot from Kraken

### Log Example to Share:
```
❌ ORDER VALIDATION FAILED [kraken] ETH-USD
   Reason: Order size $5.00 below Kraken minimum $10.00
   Side: buy, Size: 0.003, Type: base
   
Account Info:
- Balance: $75 (SAVER tier)
- Kraken API: Connected
- Permissions: All granted
```

---

## ✅ Quick Checklist

Before every trading session:

- [ ] Kraken API credentials in `.env`
- [ ] API permissions enabled (Query + Trade + Cancel)
- [ ] Balance ≥ $25 (or ≥ $100 for profitability)
- [ ] Only trading USD/USDT pairs
- [ ] Logs show "Kraken connected" ✅
- [ ] Test balance fetch works
- [ ] Tier detected in logs

---

## 🎯 Success Indicators

When everything is working:

```
✅ Kraken connected
Kraken balance: USD $250.00 + USDT $0.00 = $250.00

✅ Tier validation passed: [INCOME] $20.00 trade
📝 Placing Kraken market buy order: ETHUSD
   Size: 0.015 base, Validation: PASSED

✅ ORDER CONFIRMED:
   • Order ID (txid): O3G7XK-XXXXX-XXXXXX
   • Filled Volume: 0.015000 ETH
   • Filled Price: $1333.33
   • Status: closed
   • Balance Delta (approx): -$20.00
```

---

**Remember:** Most "failures" are actually NIJA protecting you from unprofitable trades. Trust the validation system.
