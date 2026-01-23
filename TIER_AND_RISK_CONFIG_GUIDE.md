# Account Tier and Trade Size Configuration Guide

## Overview

This guide explains the account tier management and trade size limits in the NIJA trading bot.

**⚠️ CRITICAL: Accounts below $100 should NOT be used for live independent trading.**

**💡 PUBLIC-FACING MESSAGE:**
> "NIJA AI Trading is designed for accounts starting at $100.  
> Smaller balances may connect, but full trading performance begins at Starter tier."

## Changes Made (Jan 23, 2026)

### 1. Enforced $100 Minimum for Live Trading

**Changed:** `bot/tier_config.py`
- Added `MINIMUM_LIVE_TRADING_BALANCE = 100.0`
- Added `can_trade_live()` function to validate balances
- Updated tier descriptions to reflect engineering requirements

**Why $100 Minimum?**
- Fees dominate below $100 (~1.4% round-trip on Coinbase)
- Kraken requires $10 minimum order size
- Tier enforcement blocks entries
- Users think bot is broken (it's not, it's protecting them)

### 2. Implemented PRO MODE + TIER_LOCK

**Changed:** `bot/risk_manager.py`
- Added `tier_lock` parameter to `AdaptiveRiskManager`
- Tier lock overrides balance-based tier detection
- PRO MODE provides smart execution with tier-capped risk
- **PRO MODE is invisible to users** - they don't toggle it

**How It Works:**
```
PRO MODE (smart execution) + TIER_LOCK (risk cap) = Protected retail trading
```

Users get sophisticated execution without over-leveraging small accounts.

### 3. Updated All Tier Environment Files

**Changed:** All `.env.*_tier` files
- Added `INITIAL_CAPITAL` with correct minimums
- Enabled `PRO_MODE=true` by default
- Added `TIER_LOCK=<TIER_NAME>` for risk management
- Updated minimum balance thresholds
- Updated descriptions to match problem statement

## Account Tiers

NIJA uses 6 trading tiers based on account balance:

| Tier | Balance Range | Max Risk % | Trade Size Range | Max Positions | Description |
|------|---------------|------------|------------------|---------------|-------------|
| STARTER | $50-$99 | 10-15% | $10-$25 | 1 | ⚠️ DEPRECATED - Copy trading only |
| SAVER | $100-$249 | 10% | $10-$40 | 1 | ✅ Absolute minimum (fees/minimums/risk coexist) |
| INVESTOR | $250-$999 | 5-7% | $20-$75 | 3 | Multi-position rotation without risk blocks |
| INCOME | $1,000-$4,999 | 3-5% | $30-$150 | 5 | First tier where NIJA trades as designed ⭐ |
| LIVABLE | $5,000-$24,999 | 2-3% | $50-$300 | 6 | Pro-style scaling + streak logic |
| BALLER | $25,000+ | 1-2% | $100-$1,000 | 8 | Capital deployment (institutional behavior) |

### Hard Rule (Do Not Violate Publicly)

**Accounts below $100 should NOT be advertised as "live trading."**

Below $100:
- ❌ Fees dominate (1.4% round-trip eats tiny accounts)
- ❌ Kraken rejects orders ($10 minimum can't be met)
- ❌ Tier enforcement blocks entries
- ❌ Users think bot is broken (it's not, it's protecting them)

## Configuration

### Master Account (ALWAYS BALLER Tier)

**⚠️ CRITICAL: The master account is ALWAYS BALLER tier regardless of balance.**

To enable this, set in your `.env` file:

```bash
# Master account - always BALLER tier
MASTER_ACCOUNT_TIER=BALLER
```

**Benefits for Master Account:**
- ✅ Best risk management parameters (1-2% max risk per tier guidelines)
- ✅ Highest trade size range ($100-$1,000 per tier)
- ✅ Maximum positions allowed (8 concurrent positions)
- ✅ 15% max trade size cap still applies globally

**Example: Master account with $62.49 balance:**
- Tier: BALLER (forced, not STARTER)
- Max trade size: $9.37 (15% cap applies)
- Tier guidelines: 1-2% risk
- **Note:** 15% cap ($9.37) is below BALLER tier minimum ($100)
- Trades will be limited to what the 15% cap allows

### User Accounts (Auto-Detection or Override)

#### Automatic Tier Detection (Default for User Accounts)

By default, user accounts automatically detect their tier based on balance:

```bash
# .env file for user accounts
# Leave MASTER_ACCOUNT_TIER empty or commented out for auto-detection
# MASTER_ACCOUNT_TIER=
```

**Example:**
- Balance: $62.49 → STARTER tier
- Balance: $500 → INVESTOR tier
- Balance: $5,000 → LIVABLE tier

#### Manual Tier Override for User Accounts

To force a specific tier for a user account:

```bash
# .env file
MASTER_ACCOUNT_TIER=INVESTOR
```

**Valid values:**
- `BALLER` or `MASTER` - Forces BALLER tier (recommended for master account)
- `STARTER`
- `SAVER`
- `INVESTOR`
- `INCOME`
- `LIVABLE`

### When to Use Tier Override

**Use case:** You have a small account ($62.49) but want the risk management of a higher tier:

```bash
# .env file
MASTER_ACCOUNT_TIER=INVESTOR
```

**Benefits:**
- ✅ Lower max risk per trade (5-7% vs 10-15%)
- ✅ More conservative position sizing
- ✅ Better risk management practices
- ✅ Ability to open up to 3 positions

**Trade-offs:**
- ⚠️ Higher minimum trade size ($20 vs $10)
- ⚠️ May have fewer valid setups due to minimum size requirements
- ⚠️ Some trades may be skipped if they don't meet tier minimums

## Examples

### Example 1: Master Account with BALLER Tier (Required)

```bash
# .env file
MASTER_ACCOUNT_TIER=BALLER
```

**Account:** $62.49 (Master Account)

**Tier:** BALLER (forced, always)

**Risk Parameters:**
- Max risk per trade: 1-2% (tier guidelines)
- Trade size range: $100-$1,000 (tier limits)
- Max positions: 8
- **Actual max trade:** $9.37 (15% of $62.49 - global cap applies)

**Important Notes:**
- ✅ Master account ALWAYS uses BALLER tier
- ✅ Best risk management parameters
- ⚠️ 15% cap ($9.37) is below BALLER tier minimum ($100)
- Smaller trades will execute up to the 15% cap
- This is the REQUIRED configuration for master account

### Example 2: User Account with Auto-Detection (STARTER)

```bash
# .env file for user account
# Leave MASTER_ACCOUNT_TIER empty or commented out
```

**Account:** $62.49 (User Account)

**Tier:** STARTER (auto-detected)

**Risk Parameters:**
- Max risk per trade: 10-15%
- Trade size range: $10-$25
- Max positions: 1

**Position Sizing:**
- With 15% risk limit: max $9.37 per trade
- Tier allows trades as small as $10
- ✅ Configuration compatible - trades can execute

### Example 2: Small Account with INVESTOR Tier (Override) - Not Recommended

```bash
# .env file
MASTER_ACCOUNT_TIER=INVESTOR
```

**Account:** $62.49

**Tier:** INVESTOR (forced)

**Risk Parameters:**
- Max risk per trade: 5-7%
- Trade size range: $20-$75
- Max positions: 3

**Position Sizing:**
- With 15% risk limit: max $9.37 per trade
- **⚠️ Critical Issue:** Tier minimum is $20
- **Result: No trades will execute** (balance too small for INVESTOR tier minimums)

**Recommendation:** Do not use this configuration. The 15% cap ($9.37) is below the INVESTOR tier minimum ($20), preventing all trades. Either:
1. Use auto-detection (STARTER tier) for accounts under $250
2. Deposit at least $250 to naturally qualify for INVESTOR tier

### Example 4: Medium User Account with Auto-Detection

```bash
# .env file (no override for user account)
# MASTER_ACCOUNT_TIER=
```

**Account:** $500

**Tier:** INVESTOR (auto-detected)

**Risk Parameters:**
- Max risk per trade: 5-7%
- Trade size range: $20-$75
- Max positions: 3

**Position Sizing:**
- With 15% risk limit: max $75 per trade
- Tier maximum: $75 per trade
- ✅ Full tier capabilities available

## Recommendations

### For Master Account

**Required: Always use BALLER tier**
```bash
MASTER_ACCOUNT_TIER=BALLER
```
- ✅ Best risk management parameters
- ✅ Enforced by design - master is always BALLER
- ✅ 15% max trade size cap still applies

### For User Accounts Under $100

**Option 1: Use Auto-Detection (STARTER tier) - Recommended**
```bash
# Leave MASTER_ACCOUNT_TIER commented out
```
- ✅ Allows trading with small balances
- ✅ Trades as small as $10 are permitted
- ✅ 15% cap ($9.37 for $62.49) still applies
- ⚠️ Higher max risk per tier guidelines (10-15%, but actual trades limited by 15% cap)

**Option 2: Do Not Override to Higher Tiers**
- ❌ INVESTOR tier has $20 minimum trade size
- ❌ 15% of $62.49 is only $9.37 (below minimum)
- ❌ This configuration will block all trades

**Option 3: Deposit More Funds - Best Long-Term**
- Deposit to at least $250 to qualify for INVESTOR tier naturally
- ✅ Best option for sustainable trading success

### For User Accounts $100-$249

**Recommended:** Use auto-detection (SAVER tier)
```bash
# Leave MASTER_ACCOUNT_TIER commented out for user accounts
```
- Balanced risk management (7-10%)
- Trade sizes $15-$40
- 2 concurrent positions allowed

### For User Accounts $250+

**Recommended:** Use auto-detection
- System will automatically assign appropriate tier
- Tier will upgrade as balance grows
- No manual intervention needed

## Technical Details

### Position Size Calculation

The actual position size is calculated using:

```python
position_size = min(
    balance * 0.15,  # 15% max (new limit)
    tier_max_trade_size,  # Tier-specific maximum
    calculated_size  # Based on ADX, confidence, etc.
)
```

**Factors affecting position size:**
1. Account balance (15% hard cap)
2. Tier maximum trade size
3. ADX (trend strength)
4. AI signal confidence
5. Recent trading streak
6. Market volatility
7. Current portfolio exposure

### Code References

- **Tier Configuration:** `bot/tier_config.py`
- **Risk Management:** `bot/risk_manager.py`
- **Environment Config:** `.env.example`

## Testing

Run the test suite to verify configuration:

```bash
python3 test_tier_and_risk_changes.py
```

This will validate:
- ✅ Tier override functionality
- ✅ Risk manager 15% limit
- ✅ Trade size calculations
- ✅ Tier benefit comparisons

## Troubleshooting

### Problem: No trades executing

**Possible causes:**
1. Tier minimum trade size exceeds available balance
2. All signals fail tier validation

**Solution:**
- Use auto-detection for small accounts
- Or deposit more funds to meet tier minimums

### Problem: Trades too small

**Possible causes:**
1. Using STARTER tier with very small balance
2. Low confidence signals reduce position size

**Solution:**
- Consider depositing more capital
- Wait for stronger signals (higher ADX, better confirmations)

### Problem: Want higher risk per trade

**Solution:**
- Use a lower tier (e.g., STARTER allows 10-15%)
- Note: Higher risk means potential for larger drawdowns
- 15% cap still applies regardless of tier

## Summary

The new configuration provides:

1. **Better Risk Management:** 15% max trade size (down from 20%)
2. **Tier Flexibility:** Manual override available via `MASTER_ACCOUNT_TIER`
3. **Small Account Support:** Can force conservative tiers on small balances
4. **Automatic Scaling:** Tiers auto-upgrade as balance grows

For most users, **auto-detection is recommended**. Only use manual overrides if you have specific risk management requirements.
