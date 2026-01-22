# NIJA Trading Tier System - Execution Requirements

## 🎯 Overview

NIJA uses a **tier-based execution system** to protect your capital from being eaten by trading fees. This guide explains what you need to know about tier minimums and why your trades might be blocked.

---

## 💰 Why Tier Minimums Exist

### The Fee Problem

When you place a trade, you pay fees on **both entry and exit**:

| Exchange | Entry Fee | Exit Fee | **Total Round-Trip** |
|----------|-----------|----------|----------------------|
| Coinbase | 0.60% | 0.60% | **1.20%** |
| Kraken | 0.26% | 0.26% | **0.52%** |

**Example: What happens with a $5 trade on Coinbase:**
- Entry fee: $0.03 (0.60% of $5)
- Exit fee: $0.03 (0.60% of $5)
- **Total fees: $0.06** (1.20% of $5)
- **Your trade needs to move 1.20%+ just to break even**
- **A 2% profit becomes 0.80% after fees**

This means small trades are mathematically unlikely to be profitable. NIJA prevents this by enforcing **tier-based minimums**.

---

## 🏆 NIJA Trading Tiers

### Tier Structure

Your tier is automatically determined by your **account balance**:

| Tier | Balance Range | Min Trade Size | Max Trade Size | Max Positions | Status |
|------|---------------|----------------|----------------|---------------|--------|
| **SAVER** | $100–$249 | $15 | $40 | 2 | Capital preservation + learning |
| **INVESTOR** | $250–$999 | $20 | $75 | 3 | Consistent participation |
| **INCOME** | $1k–$4.9k | $30 | $150 | 5 | Serious retail trading |
| **LIVABLE** | $5k–$24.9k | $50 | $300 | 6 | Professional-level execution |
| **BALLER** | $25k+ | $100 | $1k | 8 | Capital deployment |

### What Each Tier Means

#### SAVER Tier ($100–$249)
- **Purpose**: Capital preservation while learning the system
- **Execution**: Up to 2 positions
- **Min Trade**: $15 (fee-efficient on most exchanges)
- **✅ RECOMMENDED**: Good starting tier for new traders

#### INVESTOR Tier ($250–$999) [DEFAULT]
- **Purpose**: Consistent participation in markets
- **Execution**: Normal execution, up to 3 positions
- **Min Trade**: $20 (profitable after fees)
- **✅ RECOMMENDED**: Default tier for active trading

#### INCOME Tier ($1k–$4.9k)
- **Purpose**: Serious retail trading with active participation
- **Execution**: Optimized execution, up to 5 positions
- **Min Trade**: $30 (well above fee thresholds)
- **💎 SERIOUS TRADING**: For committed retail traders

#### LIVABLE Tier ($5k–$24.9k)
- **Purpose**: Professional-level execution
- **Execution**: Precision execution, up to 6 positions
- **Min Trade**: $50 (fees become negligible)
- **🚀 PROFESSIONAL**: Where professional execution matters

#### BALLER Tier ($25k+)
- **Purpose**: Capital deployment at scale
- **Execution**: Full deployment, up to 8 positions
- **Min Trade**: $100 (institutional-level sizing)
- **💰 ELITE**: Maximum profit potential and portfolio flexibility

---

## 🚫 Why Your Trade Was Blocked

### Common Rejection Reasons

#### 1. **Below Tier Minimum**
```
❌ ORDER VALIDATION FAILED [kraken] ETH-USD
   Reason: [INVESTOR Tier] Trade size $5.00 below tier minimum $10.00
   Account balance: $150.00
```

**What this means:**
- Your account has $150, putting you in INVESTOR tier
- INVESTOR tier requires minimum $10 trades
- You tried to place a $5 trade
- **Solution**: Wait for a stronger signal or increase position size to $10+

#### 2. **Below Account Minimum**
```
❌ ORDER VALIDATION FAILED [kraken] BTC-USD
   Reason: Account balance $15.00 below minimum tier requirement $25.00
   Cannot execute trades.
```

**What this means:**
- Your account has less than $25
- NIJA requires minimum $25 to trade (SAVER tier minimum)
- **Solution**: Deposit more funds to reach $25 minimum

#### 3. **Below Exchange Minimum**
```
❌ ORDER VALIDATION FAILED [kraken] SOL-USD
   Reason: Order size $8.00 below Kraken minimum $10.00
```

**What this means:**
- Kraken exchange requires minimum $10 per trade
- You tried to place an $8 trade
- **Solution**: Increase trade size to $10+ or wait for stronger signal

#### 4. **Unsupported Symbol**
```
❌ ORDER VALIDATION FAILED [kraken] SHIB-BUSD
   Reason: Kraken only supports USD/USDT pairs. Symbol 'SHIB-BUSD' is not supported.
```

**What this means:**
- Kraken only trades pairs ending in USD or USDT
- BUSD pairs are not supported on Kraken
- **Solution**: This trade will be skipped (or routed to Coinbase if configured)

---

## 💡 Understanding the Execution Flow

### When a Signal is Generated

```
1. NIJA Strategy identifies buy/sell signal
   ↓
2. Calculate position size based on your tier
   ↓
3. VALIDATE: Check all requirements
   ├─ Symbol format (BTC → XBT for Kraken)
   ├─ Exchange minimum ($10 on Kraken)
   ├─ Tier minimum ($2-$50 based on balance)
   ├─ Balance sufficiency
   └─ Tier risk limits
   ↓
4. IF ALL PASS:
   ├─ Convert symbol to exchange format
   ├─ Place order via AddOrder API
   ├─ Wait for txid confirmation
   ├─ Verify order filled
   └─ Log trade details
   ↓
5. IF ANY FAIL:
   └─ BLOCK order and log reason
```

### Order Confirmation (What You'll See)

**Successful Order:**
```
✅ Tier validation passed: [INCOME] $20.00 trade
📝 Placing Kraken market buy order: ETHUSD
   Size: 0.015 base, Validation: PASSED
   
✅ ORDER CONFIRMED:
   • Order ID (txid): O3G7XK-XXXXX-XXXXXX
   • Filled Volume: 0.015 ETH
   • Filled Price: $1333.33
   • Status: closed
   • Balance Delta (approx): -$20.00
```

**Blocked Order:**
```
❌ ORDER VALIDATION FAILED [kraken] ETH-USD
   Reason: [SAVER Tier] Trade size $1.50 below tier minimum $2.00
   Side: buy, Size: 0.001, Type: base
```

---

## 🔧 How to Maximize Your Trading

### 1. **Understand Your Tier**

Check your current tier based on balance:
- < $100: ❌ Cannot trade (deposit more)
- $100–$249: SAVER (capital preservation + learning)
- $250–$999: INVESTOR (consistent participation - default)
- $1k–$4.9k: INCOME ⭐ (serious retail trading)
- $5k–$24.9k: LIVABLE (professional-level execution)
- $25k+: BALLER (capital deployment)

### 2. **Deposit to Reach Next Tier**

Each tier unlock gives you:
- ✅ Lower minimum trade sizes (more opportunities)
- ✅ More concurrent positions
- ✅ Better risk/reward ratios
- ✅ Higher profit potential

**Example tier progression:**
- Start: $75 (SAVER) → Limited, $2 min trades
- Deposit $25 → $100 (INVESTOR) → $10 min trades, 3 positions
- Grow to $250 (INCOME) → $15 min trades, 5 positions ⭐

### 3. **Use Kraken for Lower Fees**

| Exchange | Round-Trip Fees | Minimum Trade |
|----------|-----------------|---------------|
| Kraken | 0.52% | $10 |
| Coinbase | 1.20% | $25 |

**Kraken advantages:**
- 💰 **2.3x lower fees** (0.52% vs 1.20%)
- 💰 **Lower minimum** ($10 vs $25)
- 💰 **Better for small accounts** (SAVER-INVESTOR tiers)

### 4. **Wait for Quality Signals**

NIJA will reject trades that don't meet minimums. This is **protecting you**.

**Don't:**
- ❌ Try to force tiny positions
- ❌ Disable tier limits (you'll lose to fees)
- ❌ Expect every signal to execute

**Do:**
- ✅ Trust the tier system
- ✅ Wait for stronger signals
- ✅ Let NIJA filter out unprofitable trades

---

## 📊 Exchange-Specific Requirements

### Kraken
- **Minimum**: $10 per trade
- **Supported Pairs**: Only USD and USDT quotes
  - ✅ BTC-USD, ETH-USD, SOL-USDT
  - ❌ BTC-BUSD, ETH-EUR (not supported)
- **Symbol Format**: Automatic conversion (BTC → XBT)
- **Confirmation**: txid required and verified

### Coinbase
- **Minimum**: $25 per trade (higher fees)
- **Supported Pairs**: All USD, USDT, USDC pairs
- **Symbol Format**: XXX-YYY (e.g., BTC-USD)
- **Confirmation**: order_id required

---

## ❓ FAQ

### Q: Why can't I trade with $10?
**A:** You can! But only if you're on **INVESTOR tier or higher** ($100+ balance) and trading on **Kraken**. Coinbase requires $25 minimum.

### Q: Can I disable tier limits?
**A:** No. Tier limits protect you from fee destruction. A $3 trade on Coinbase loses $0.04 to fees immediately. You need a 1.3% move just to break even.

### Q: Why does NIJA skip some signals?
**A:** Because executing them would **lose money to fees**. NIJA only executes trades that have a realistic chance of being profitable after fees.

### Q: What if I want to trade smaller amounts?
**A:** Options:
1. **Deposit more** to reach INVESTOR tier ($100+)
2. **Use Kraken** (lower $10 minimum vs Coinbase $25)
3. **Wait for stronger signals** that warrant larger positions

### Q: How do I see my tier?
**A:** Your tier is shown in the logs when a trade is placed:
```
✅ Tier validation passed: [INCOME] $20.00 trade
```

### Q: What's the minimum to start?
**A:** **$25** (SAVER tier). Anything less cannot execute trades.

---

## 🎓 Key Takeaways

1. **Tier system exists to protect your capital from fees**
2. **Minimum $25 to trade** (SAVER tier)
3. **$100+ recommended** for consistent profitability (INVESTOR tier)
4. **Use Kraken** for lower fees (0.52% vs 1.20%)
5. **Trust the system** when it blocks unprofitable trades
6. **Deposit to next tier** for more opportunities

---

## 🔗 Related Documentation

- `RISK_PROFILES_GUIDE.md` - Detailed tier risk profiles
- `KRAKEN_TRADING_GUIDE.md` - Kraken-specific trading information
- `SMALL_ACCOUNT_QUICKSTART.md` - Getting started with small balances
- `USER_BALANCE_GUIDE.md` - Understanding balance tiers

---

**Questions?** Check your logs for specific rejection reasons, or review the tier minimums above.

**Remember:** Every blocked trade is NIJA protecting you from fee destruction. Trust the system.
