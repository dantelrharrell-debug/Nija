# Account Tier and Trade Size Configuration Guide

## Overview

This guide explains the recent changes to account tier management and trade size limits in the NIJA trading bot.

## Changes Made (Jan 22, 2026)

### 1. Reduced Maximum Trade Size to 15%

**Changed:** `bot/risk_manager.py`
- Previous: `max_position_pct = 0.20` (20%)
- New: `max_position_pct = 0.15` (15%)

This ensures that individual trades cannot exceed 15% of the account balance, providing better risk management for smaller accounts.

**Example:**
- Balance: $62.49
- Max trade size (15%): $9.37
- Previous max (20%): $12.50

### 2. Added Account Tier Override

**Changed:** `bot/tier_config.py`
- Added `MASTER_ACCOUNT_TIER` environment variable support
- Allows forcing a specific tier regardless of account balance

## Account Tiers

NIJA uses 6 trading tiers based on account balance:

| Tier | Balance Range | Max Risk % | Trade Size Range | Max Positions |
|------|---------------|------------|------------------|---------------|
| STARTER | $50-$99 | 10-15% | $10-$25 | 1 |
| SAVER | $100-$249 | 7-10% | $15-$40 | 2 |
| INVESTOR | $250-$999 | 5-7% | $20-$75 | 3 |
| INCOME | $1,000-$4,999 | 3-5% | $30-$150 | 5 |
| LIVABLE | $5,000-$24,999 | 2-3% | $50-$300 | 6 |
| BALLER | $25,000+ | 1-2% | $100-$1,000 | 8 |

## Configuration

### Automatic Tier Detection (Default)

By default, NIJA automatically detects your tier based on your account balance:

```bash
# .env file
# Leave MASTER_ACCOUNT_TIER empty or commented out
# MASTER_ACCOUNT_TIER=
```

**Example:**
- Balance: $62.49 → STARTER tier
- Balance: $500 → INVESTOR tier
- Balance: $5,000 → LIVABLE tier

### Manual Tier Override

To force a specific tier (e.g., for better risk management on small accounts):

```bash
# .env file
MASTER_ACCOUNT_TIER=INVESTOR
```

**Valid values:**
- `STARTER`
- `SAVER`
- `INVESTOR`
- `INCOME`
- `LIVABLE`
- `BALLER`

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

### Example 1: Small Account with STARTER Tier (Auto-Detected)

```bash
# .env file (no override)
# MASTER_ACCOUNT_TIER=
```

**Account:** $62.49

**Tier:** STARTER (auto-detected)

**Risk Parameters:**
- Max risk per trade: 10-15%
- Trade size range: $10-$25
- Max positions: 1

**Position Sizing:**
- With 15% risk limit: max $9.37 per trade
- Actual trades will be smaller based on signal strength

### Example 2: Small Account with INVESTOR Tier (Override)

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
- However, tier minimum is $20
- ⚠️ This means NO TRADES will execute (balance too small for INVESTOR tier)

### Example 3: Medium Account with Auto-Detection

```bash
# .env file (no override)
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

### For Accounts Under $100

**Option 1: Use Auto-Detection (STARTER tier)**
```bash
# Leave MASTER_ACCOUNT_TIER commented out
```
- ✅ Allows trading with small balances
- ✅ Trades as small as $10 are permitted
- ⚠️ Higher risk per trade (10-15%)

**Option 2: Deposit More Funds**
- Deposit to at least $250 to qualify for INVESTOR tier naturally
- ✅ Best option for long-term trading success

### For Accounts $100-$249

**Recommended:** Use auto-detection (SAVER tier)
```bash
# Leave MASTER_ACCOUNT_TIER commented out
```
- Balanced risk management (7-10%)
- Trade sizes $15-$40
- 2 concurrent positions allowed

### For Accounts $250+

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
