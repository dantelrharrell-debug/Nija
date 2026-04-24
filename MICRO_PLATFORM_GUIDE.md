# NIJA Micro-Master Guide ($25-$50 Platform Accounts)

## Overview

This guide explains how to operate a NIJA platform account with **$25-$50 capital** (Micro-Master mode).

### Who Is This For?

- **Learning**: Want to understand platform account operations with minimal risk
- **Testing**: Testing copy trading strategies before scaling up
- **Budget-Conscious**: Limited capital but want to provide copy trading signals
- **Upgrade Path**: Planning to grow capital to higher tiers

### Critical Reality Check

⚠️ **At $25-$50, you are operating at the ABSOLUTE MINIMUM for platform accounts.**

**What This Means:**
- Fees consume 1-2% of every trade (significant impact on profitability)
- Single position only (no rotation, no diversification)
- Kraken incompatible ($10 minimum trade requirement)
- Best used for **copy trading** where users have larger accounts
- NOT recommended for long-term independent trading

**Recommended Path:** Save profits and upgrade to:
- **$100+ (SAVER tier)** - Minimum viable platform account
- **$250+ (INVESTOR tier)** - Full multi-position support
- **$1,000+ (INCOME tier)** - NIJA operates as designed

---

## Tier Structure & Hard Minimums

### Master Funding Tiers

| Tier | Balance Range | Description | Hard Minimum |
|------|---------------|-------------|--------------|
| **MICRO_MASTER** | $25-$49 | Ultra-minimal, Coinbase only, single position | $25 |
| **STARTER** | $50-$99 | Learning mode, copy trading recommended | $50 |
| **SAVER** | $100-$249 | Minimum viable master, single position | $100 |
| **INVESTOR** | $250-$999 | Multi-position support, rotation enabled | $250 |
| **INCOME** | $1,000-$4,999 | Professional-grade platform | $1,000 |
| **LIVABLE** | $5,000-$24,999 | Pro-style scaling | $5,000 |
| **BALLER** | $25,000+ | Institutional-quality platform | $25,000 |

### MICRO_MASTER Operational Constraints

When operating in **MICRO_MASTER mode** ($25-$49), the following limits are enforced:

```python
ABSOLUTE_MINIMUM: $25.00
RECOMMENDED_MINIMUM: $50.00
MAX_TRADE_SIZE: 40% of balance
MIN_TRADE_SIZE: $5.00
MAX_POSITIONS: 1 (single position only)
EXCHANGE: Coinbase only (Kraken not compatible)
COPY_TRADING: Best practice (provides value to users with larger accounts)
```

**Why $25 is the Absolute Floor:**
1. Below $25, even $5 trades represent 20%+ position sizes
2. Fee impact becomes catastrophic (2-3% per round trip)
3. Exchange APIs may reject micro-orders
4. Impossible to maintain reserve requirements

---

## Setup Instructions

### Step 1: Fund Your Account

**Minimum:** $25 (absolute floor)
**Recommended:** $50 (more stable operation)
**Optimal:** $100+ (upgrade to SAVER tier)

**Important:** Deposit to **Coinbase Advanced Trade** (NOT Coinbase Pro, NOT Kraken)

### Step 2: Configure Environment

Copy the micro-master preset:

```bash
cp .env.micro_master .env
```

### Step 3: Add API Credentials

Edit `.env` and add your Coinbase credentials:

```bash
# Required: Coinbase Advanced Trade API
COINBASE_API_KEY=your_key_here
COINBASE_API_SECRET=your_secret_here
```

**Do NOT add Kraken credentials** - Kraken is incompatible with micro-master mode.

### Step 4: Verify Configuration

Check that these settings are correct in `.env`:

```bash
IS_MASTER_ACCOUNT=true
MASTER_BROKER=COINBASE
MICRO_MASTER_MODE=true
MAX_CONCURRENT_POSITIONS=1
MIN_CASH_TO_BUY=5.00
INITIAL_CAPITAL=50  # Or your actual starting balance
```

### Step 5: Start NIJA

```bash
./start.sh
```

### Step 6: Monitor Initial Operation

Watch the logs to confirm proper operation:

```bash
tail -f logs/nija.log
```

**Look for:**
- ✅ "MICRO-MASTER MODE ACTIVE"
- ✅ "Master Operational Limits (MICRO_MASTER)"
- ✅ "Max Trade Size: 40.0% of balance"
- ✅ "Max Positions: 1"

**Red Flags:**
- ❌ "Kraken platform broker detected" (should use Coinbase only)
- ❌ "Trade size below exchange minimum" (increase MIN_CASH_TO_BUY)
- ❌ "Insufficient balance" (need to deposit more)

---

## Trading with Micro Capital

### Position Sizing

**Example: $30 Master Balance**

```
Max Trade Size: $30 × 40% = $12.00
Min Trade Size: $5.00 (Coinbase minimum)
Typical Trade: $8-10 (26-33% of balance)
```

**Example: $50 Master Balance**

```
Max Trade Size: $50 × 40% = $20.00
Min Trade Size: $5.00
Typical Trade: $12-15 (24-30% of balance)
```

### Trade Execution Strategy

**With $25-$50, you MUST be selective:**

1. **Only trade 5/6 or 6/6 signal quality** (skip 3/6 or 4/6 signals)
2. **Use tight stops** (1.0% - 1.5% maximum)
3. **Take profits quickly** (+2% → exit 50%, +3.5% → exit all)
4. **Avoid choppy markets** (require strong trends, ADX > 25)
5. **Trade liquid pairs only** (BTC-USD, ETH-USD, SOL-USD)

### Fee Management

**Coinbase Fees (Advanced Trade):**
- Taker (market orders): ~0.60%
- Maker (limit orders): ~0.40%
- Round-trip: ~0.80-1.20%

**Impact on $10 Trade:**
- Entry fee: $0.04-0.06
- Exit fee: $0.04-0.06
- Total fees: $0.08-0.12 (0.8-1.2% of trade)

**To Overcome Fees:** Need +1.5% minimum profit

**Strategy:**
- Use LIMIT orders (lower fees)
- Take profits at +2% minimum
- Avoid frequent trading (fees add up)

---

## Copy Trading with Micro-Masters

### Why Micro-Masters Work for Copy Trading

Even with $30 capital, you can provide valuable signals to users with larger accounts.

**Example:**

```
Master: $30 balance, $10 trade (33% position)
User 1: $100 balance → $33 trade (same 33% ratio)
User 2: $500 balance → $167 trade (same 33% ratio)
User 3: $1,000 balance → $333 trade (same 33% ratio)
```

**Key Point:** Your small $10 trade scales proportionally to user balances.

### Configuring Copy Trading

**Master Settings (You):**
```bash
IS_MASTER_ACCOUNT=true
COPY_TRADING_MODE=MASTER_SIGNAL
PRO_MODE=true
```

**User Settings (Your Copy Traders):**
```bash
IS_MASTER_ACCOUNT=false
COPY_TRADING_MODE=MASTER_FOLLOW
COPY_FROM_MASTER=true
PRO_MODE=true
```

### Best Practices for Micro-Master Copy Trading

1. **Communicate Limitations:** Tell users you're operating with micro capital
2. **Trade Quality Over Quantity:** Only take high-conviction signals
3. **Document Strategy:** Share your entry/exit rules
4. **Transparent Performance:** Report wins/losses honestly
5. **Upgrade When Possible:** Grow to $100+ for more reliability

---

## Safety & Risk Management

### Automatic Protections

Micro-master mode enforces:

```python
✅ Maximum 1 concurrent position
✅ Maximum 40% position size
✅ Minimum $5 trade size
✅ Daily loss limit: 5%
✅ Consecutive loss breaker: 2 losses
✅ Emergency stop: $20 balance
✅ Burn-down mode after 1 loss
```

### Manual Risk Controls

**You should also:**
- ✅ Start with $50 if possible (not $25)
- ✅ Paper trade first to learn
- ✅ Trade 1-2 times per day maximum
- ✅ Never increase position size after losses
- ✅ Keep detailed trading journal
- ✅ Set realistic profit goals (+2-5% per trade)

### When to Stop Trading

**Stop immediately if:**
- ❌ 2 consecutive losses
- ❌ Daily loss exceeds 5%
- ❌ Balance drops below $20
- ❌ Multiple trade rejections
- ❌ Emotional trading decisions

**Take a break, review what happened, adjust strategy.**

---

## Troubleshooting

### "Trade size below exchange minimum"

**Problem:** Trying to trade less than $5
**Solution:** Increase `MIN_CASH_TO_BUY=5.00` or higher

### "Kraken rejected order: Minimum $10"

**Problem:** Attempting to use Kraken (not compatible)
**Solution:** Change to `MASTER_BROKER=COINBASE`

### "Insufficient balance for trade"

**Problem:** Not enough cash after position sizing
**Solution:**
- Reduce `MAX_POSITION_SIZE_PCT` to 30% or 35%
- Increase account balance
- Wait for current position to close

### "Maximum positions reached (1)"

**Problem:** Trying to open second position
**Solution:** This is intentional. Wait for first position to close.

### "Signal score 4/6 - trade skipped"

**Problem:** Signal quality too low for micro capital
**Solution:** This is protective. Only 5/6 and 6/6 signals execute.

---

## Upgrade Path

### From Micro-Master ($25-$50) to SAVER ($100+)

**Goal:** Double or triple your capital to $100

**Strategy:**
1. **Compound Profits:** Don't withdraw, let profits build
2. **Conservative Trading:** Aim for steady 2-3% wins
3. **Deposit When Possible:** Add $10-20 monthly
4. **Track Progress:** Monitor balance weekly

**Timeline:**
- Aggressive: 4-8 weeks (risky)
- Conservative: 8-16 weeks (safer)
- Mixed: Add deposits + compound (fastest)

### Benefits of Upgrading to SAVER ($100+)

Once you reach $100:

```bash
# Update .env
INITIAL_CAPITAL=100
PLATFORM_ACCOUNT_TIER=SAVER
MICRO_MASTER_MODE=false  # Disable micro mode
MIN_CASH_TO_BUY=10.00  # Kraken compatible now
```

**New Capabilities:**
- ✅ Can use Kraken (lower fees)
- ✅ Slightly larger trade sizes
- ✅ More reliable operation
- ✅ Better copy trading stability
- ✅ Reduced fee impact

### Ultimate Goal: INVESTOR ($250+)

At $250+, you unlock:
- **Multi-position trading** (up to 3 positions)
- **Position rotation** (close weak, open strong)
- **Full NIJA features** (as designed)
- **Professional copy trading** (institutional quality)

---

## Frequently Asked Questions

### Q: Can I use Kraken instead of Coinbase?

**A:** No. Kraken requires $10 minimum trades. With $25-50 balance, this would be 20-40% positions (too risky). Coinbase allows $5 minimum trades.

### Q: Why can't I open multiple positions?

**A:** With $25-50 capital, multiple positions would create:
- Position sizes too small (fees dominate)
- Risk concentration (unable to manage properly)
- Exchange rejection (below minimums)

### Q: Is $25 really enough to operate?

**A:** It's the absolute minimum. We recommend $50+. Below $25, operational constraints make trading impractical.

### Q: How much can I realistically profit with $30?

**A:** Be realistic:
- Good week: +$3-5 (10-15%)
- Bad week: -$3-5 (10-15%)
- Monthly: Aim for +$5-10 (15-30%)

**Focus on learning and growing capital, not profits.**

### Q: Should I trade alone or use copy trading?

**A:** Copy trading is recommended. Even with $30, you can provide valuable signals to users with larger accounts. Solo trading at $30 is educational but not optimal.

### Q: When should I upgrade to SAVER tier?

**A:** As soon as you reach $100. Benefits:
- More stable operation
- Kraken compatibility (lower fees)
- Better positioning flexibility

### Q: Can I start with $15 or $20?

**A:** No. $25 is the absolute minimum. Below $25:
- Trade sizes too small
- Fees catastrophic
- Exchange rejections
- Unable to maintain reserves

**Recommendation:** Save up to $50 before starting.

---

## Advanced Topics

### Understanding Master Funding Rules

NIJA enforces **hard minimums** per tier to prevent:
- ❌ Exchange order rejections
- ❌ Position lockouts
- ❌ Unreliable copy trading signals
- ❌ Fee-dominated unprofitable trading

**Validation happens at startup:**

```python
from bot.tier_config import validate_master_minimum_funding

is_valid, msg, rules = validate_master_minimum_funding(balance=30.0)

if not is_valid:
    print(f"❌ Cannot operate: {msg}")
else:
    print(f"✅ {msg}")
    print(f"Max Trade: ${rules.max_trade_size_pct}%")
    print(f"Max Positions: {rules.max_positions}")
```

### Programmatic Access

```python
from bot.tier_config import (
    get_master_funding_tier,
    get_master_trade_limits,
    is_micro_master
)

# Check your tier
balance = 35.0
tier = get_master_funding_tier(balance)
print(f"Tier: {tier}")  # Output: MICRO_MASTER

# Get trade limits
limits = get_master_trade_limits(balance, exchange='coinbase')
print(f"Min Trade: ${limits['min_trade_size']:.2f}")
print(f"Max Trade: ${limits['max_trade_size']:.2f}")

# Check if micro-master mode
if is_micro_master(balance):
    print("🔧 MICRO-MASTER MODE ACTIVE")
```

---

## Summary

### ✅ Micro-Master Can Work If:
- You start with $50 (not $25)
- You use Coinbase (not Kraken)
- You trade selectively (5/6+ signals only)
- You have realistic expectations
- You plan to upgrade to $100+ soon
- You use it for copy trading

### ❌ Micro-Master Won't Work If:
- Balance below $25
- Trying to use Kraken
- Expecting large profits
- Opening multiple positions
- Trading low-quality signals
- No upgrade plan

### 🎯 Recommended Approach:
1. Start with $50 (not $25)
2. Trade 1-2 high-quality setups per day
3. Use tight stops (1-1.5%)
4. Take profits at +2-3%
5. Compound profits
6. Upgrade to SAVER ($100) within 2-3 months
7. Upgrade to INVESTOR ($250) within 6 months

**Remember:** Micro-master mode is a **learning tier** and **stepping stone** to higher tiers. It's not designed for long-term operation.

**Goal:** Grow capital → Upgrade tier → Unlock full NIJA capabilities

---

## Support

**Issues?**
- Check logs: `tail -f logs/nija.log`
- Review configuration: `cat .env | grep MICRO`
- Validate balance: Ensure $25+ deposited
- Test API: Verify Coinbase credentials

**Questions?**
- Review STARTER_SAFE_PROFILE.md
- Read TIER_AND_RISK_CONFIG_GUIDE.md
- Check GETTING_STARTED.md

---

**Version:** 1.0
**Date:** January 23, 2026
**Author:** NIJA Trading Systems
