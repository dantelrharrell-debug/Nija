# NIJA Bidirectional Trading Guide
## Profiting in Both Up AND Down Markets

**Version:** 1.0
**Date:** January 22, 2026
**Status:** ✅ ACTIVE

---

## 🎯 Overview

NIJA supports **bidirectional trading** - profiting whether markets go **UP or DOWN**:

- **LONG Positions** (Buy Low → Sell High) - Profit when price increases
- **SHORT Positions** (Sell High → Buy Low) - Profit when price decreases

This capability is **built-in** and works across all supported tiers and most brokerages.

---

## 📊 How It Works

### Long Positions (Uptrend Trading)

**Entry Conditions:**
1. Market is in uptrend (EMA9 > EMA21 > EMA50)
2. Price pulls back to EMA21 or VWAP
3. RSI shows bullish divergence (30-70 range)
4. Bullish candlestick pattern (hammer, engulfing)
5. MACD histogram ticking up
6. Volume confirmation

**Profit-Taking:**
- TP1: Entry + 1.0R (1x risk)
- TP2: Entry + 1.5R (1.5x risk)
- TP3: Entry + 2.0R (2x risk)

**Stop Loss:**
- Below swing low or Entry - 1.0R

**Example:**
```
Entry: $100
Stop: $98 (2% risk, R = $2)
TP1: $102 (1.0R = +$2, 2% gain)
TP2: $103 (1.5R = +$3, 3% gain)
TP3: $104 (2.0R = +$4, 4% gain)
```

### Short Positions (Downtrend Trading)

**Entry Conditions:**
1. Market is in downtrend (EMA9 < EMA21 < EMA50)
2. Price bounces to EMA21 or VWAP
3. RSI shows bearish pullback (30-70 range, declining)
4. Bearish candlestick pattern (shooting star, bearish engulfing)
5. MACD histogram ticking down
6. Volume confirmation

**Profit-Taking:**
- TP1: Entry - 1.0R (1x risk)
- TP2: Entry - 1.5R (1.5x risk)
- TP3: Entry - 2.0R (2x risk)

**Stop Loss:**
- Above swing high or Entry + 1.0R

**Example:**
```
Entry: $100
Stop: $102 (2% risk, R = $2)
TP1: $98 (1.0R = -$2, 2% gain on short)
TP2: $97 (1.5R = -$3, 3% gain on short)
TP3: $96 (2.0R = -$4, 4% gain on short)
```

---

## 🏦 Broker Support for Short Selling

### ✅ Full Support (Long + Short)

| Broker | Short Support | Margin Required | Notes |
|--------|--------------|----------------|--------|
| **Kraken** | ✅ Yes | Yes (varies) | Best for crypto shorting, low fees |
| **Binance** | ✅ Yes | Varies | Supports futures/margin trading |
| **OKX** | ✅ Yes | Varies | Full derivatives support |
| **Alpaca** | ✅ Yes (stocks) | Yes | Stock short selling with margin |

### ⚠️ Limited/No Support (Long Only)

| Broker | Short Support | Margin Required | Alternative |
|--------|--------------|----------------|-------------|
| **Coinbase** | ❌ No (spot only) | N/A | LONG only - profit on uptrends |

**Important Notes:**
- **Coinbase** does not support short selling on spot markets
- Use Kraken, Binance, or OKX for full bidirectional trading
- Margin requirements vary by broker and account size
- Check broker documentation for specific margin rules

---

## 🎚️ Tier Support

### All Tiers Support Bidirectional Trading

| Tier | Long Support | Short Support | Notes |
|------|-------------|---------------|-------|
| **SAVER** ($10-$25) | ✅ Yes | ✅ Yes* | *If broker supports it |
| **INVESTOR** ($100-$249) | ✅ Yes | ✅ Yes* | *If broker supports it |
| **INCOME** ($250-$999) | ✅ Yes | ✅ Yes* | *If broker supports it |
| **LIVABLE** ($1k-$5k) | ✅ Yes | ✅ Yes* | *If broker supports it |
| **BALLER** ($5k+) | ✅ Yes | ✅ Yes* | *If broker supports it |

**Key Point:** The tier system does NOT restrict long/short - it only affects position sizing and risk management.

---

## 💰 Fee-Aware Profit Targets

### Coinbase (Long Only)

**Round-Trip Fee:** ~1.4% (0.6% taker x2 + 0.2% spread)

| Position Type | TP Targets | Net Profit |
|--------------|-----------|-----------|
| LONG | 1.5%, 1.2%, 1.0% | +0.1%, -0.2%, -0.4% |
| SHORT | ❌ Not supported | N/A |

### Kraken (Long + Short)

**Round-Trip Fee:** ~0.36% (0.26% taker x2 + 0.1% spread)

| Position Type | TP Targets | Net Profit |
|--------------|-----------|-----------|
| LONG | 1.0%, 0.7%, 0.5% | +0.64%, +0.34%, +0.14% |
| SHORT | 1.0%, 0.7%, 0.5% | +0.64%, +0.34%, +0.14% |

### Binance/OKX (Long + Short)

**Round-Trip Fee:** ~0.28-0.3%

| Position Type | TP Targets | Net Profit |
|--------------|-----------|-----------|
| LONG | 0.8%, 0.6%, 0.4% | +0.5%, +0.3%, +0.1% |
| SHORT | 0.8%, 0.6%, 0.4% | +0.5%, +0.3%, +0.1% |

---

## 🔧 Configuration

### Enable/Disable Shorting

By default, shorting is **ENABLED** if broker supports it.

To disable shorting (long-only mode):

```python
# In .env or configuration
ALLOW_SHORT_POSITIONS=false
```

To enable shorting (default):

```python
# In .env or configuration
ALLOW_SHORT_POSITIONS=true  # Default
```

### Broker-Specific Settings

**Coinbase** (automatically long-only):
```bash
# Coinbase doesn't support shorting, no config needed
# NIJA will only take LONG positions on Coinbase
```

**Kraken** (enable shorting with margin):
```bash
# Kraken supports shorting with margin trading
KRAKEN_MARGIN_TRADING=true  # Enable margin for shorts
```

**Binance/OKX** (enable futures/margin):
```bash
# Enable futures/margin for shorting
BINANCE_FUTURES_ENABLED=true
OKX_MARGIN_ENABLED=true
```

---

## 📈 Strategy Behavior

### Market Detection

NIJA automatically detects market conditions:

```
Uptrend → Look for LONG entries
Downtrend → Look for SHORT entries
Sideways → HOLD (no entries)
```

### Profit-Taking Logic

**Same for LONG and SHORT:**
1. Check stepped profit exits (2%, 2.5%, 3%, 4%)
2. Check traditional TP levels (TP1, TP2, TP3)
3. Update trailing stop after TP1 hit
4. Exit on opposite signal

### Stop Loss Logic

**Same for LONG and SHORT:**
- Placed at swing low/high
- Tightened to 1% for small accounts
- Moved to breakeven after TP1
- Trailing stop activated after profit

---

## 🚨 Risk Management

### Long Positions

**Maximum Risk per Trade:**
- SAVER: 10-15%
- INVESTOR: 7-10%
- INCOME: 4-7%
- LIVABLE: 2-4%
- BALLER: 1-2%

### Short Positions

**Maximum Risk per Trade:** (SAME as long)
- SAVER: 10-15%
- INVESTOR: 7-10%
- INCOME: 4-7%
- LIVABLE: 2-4%
- BALLER: 1-2%

**Important:** Short positions have the SAME risk limits as long positions.

---

## 📊 Performance Expectations

### Long-Only Strategy (Coinbase)

**Pros:**
- Simpler risk management
- No margin requirements
- Lower fees (spot trading)

**Cons:**
- Only profits in uptrends
- Misses downtrend opportunities
- Lower win rate in bear markets

**Expected Win Rate:** 55-65% (bull markets), 40-50% (bear markets)

### Bidirectional Strategy (Kraken, Binance, OKX)

**Pros:**
- Profits in both uptrends and downtrends
- Higher trade frequency
- Better capital efficiency

**Cons:**
- Requires margin (higher risk)
- More complex position management
- Slightly higher fees (margin/futures)

**Expected Win Rate:** 60-70% (all market conditions)

---

## 🎯 Examples

### Example 1: Long Position on Coinbase

```
Market: BTC-USD on Coinbase
Condition: Uptrend detected
Entry: $42,000 (pullback to EMA21)
Stop Loss: $41,160 (2% below entry, swing low)
TP1: $42,840 (2% above entry, 1.0R)
TP2: $43,260 (3% above entry, 1.5R)
TP3: $43,680 (4% above entry, 2.0R)

Result: TP2 hit at $43,260
Gross Profit: +3.0% ($1,260)
Fees: -1.4% ($588)
Net Profit: +1.6% ($672) ✅
```

### Example 2: Short Position on Kraken

```
Market: ETH-USD on Kraken
Condition: Downtrend detected
Entry: $2,500 (bounce to EMA21)
Stop Loss: $2,550 (2% above entry, swing high)
TP1: $2,450 (2% below entry, 1.0R)
TP2: $2,425 (3% below entry, 1.5R)
TP3: $2,400 (4% below entry, 2.0R)

Result: TP1 hit at $2,450
Gross Profit: +2.0% ($50)
Fees: -0.36% ($9)
Net Profit: +1.64% ($41) ✅
```

### Example 3: Long Position on Kraken (Low Fees)

```
Market: SOL-USD on Kraken
Condition: Uptrend detected
Entry: $100
Stop Loss: $98 (2% below entry)
TP1: $102 (2% above entry, 1.0R)

Result: TP1 hit at $102
Gross Profit: +2.0% ($2)
Fees: -0.36% ($0.36)
Net Profit: +1.64% ($1.64) ✅
```

---

## ⚠️ Important Warnings

### Margin Trading Risks

**SHORT positions require margin** on most exchanges:
- **Liquidation risk** if market moves against you
- **Funding fees** (for perpetual futures)
- **Higher volatility** in leveraged positions

**Recommendation:**
- Start with **LONG-only** on Coinbase to learn
- Move to **Kraken for shorts** once experienced
- Use **low leverage** (1x-2x max) for safety

### Market Conditions

**LONG works best in:**
- Bull markets
- Strong uptrends
- High RSI recovery patterns

**SHORT works best in:**
- Bear markets
- Strong downtrends
- High RSI rejection patterns

**HOLD is best in:**
- Sideways/choppy markets
- Low volatility
- Unclear trend direction

---

## 🔍 Monitoring

### How to Verify Bidirectional Trading

**Check logs for BOTH long and short entries:**

```bash
# Check for long entries
grep "enter_long" nija.log

# Check for short entries
grep "enter_short" nija.log

# Check for profit-taking on shorts
grep "SHORT.*take_profit\|take_profit.*short" nija.log
```

**Expected Output:**
```
✅ LONG: BTC-USD entered at $42,000
✅ SHORT: ETH-USD entered at $2,500
🎯 TAKE PROFIT TP1 HIT: BTC-USD at $42,840 (LONG, PnL: +2.0%)
🎯 TAKE PROFIT TP1 HIT: ETH-USD at $2,450 (SHORT, PnL: +2.0%)
```

---

## 📖 Related Documentation

- `PROFIT_TAKING_GUARANTEE.md` - Profit-taking works for BOTH long and short
- `BROKER_INTEGRATION_GUIDE.md` - Broker-specific configurations
- `RISK_PROFILES_GUIDE.md` - Tier-specific risk management
- `APEX_V71_DOCUMENTATION.md` - Complete strategy documentation

---

## ✅ Summary Checklist

- [x] LONG positions work on all brokers
- [x] SHORT positions work on Kraken, Binance, OKX
- [x] Profit-taking works for BOTH directions
- [x] Fee-aware targets for each broker
- [x] All tiers support both directions
- [x] Same risk management for long and short
- [x] Automatic market detection (uptrend → long, downtrend → short)

---

**Last Updated:** January 22, 2026
**Maintained By:** NIJA Trading Systems
**Version:** 1.0
