# BALLER Tier Trade Size Calculation at $62.49

**Date**: January 22, 2026
**Analysis**: Safe trade size for BALLER tier with $62.49 balance

---

## Executive Summary

**Question**: What is the exact safe trade size for BALLER tier at $62.49 using the bot's fee/safety rules?

**Answer**: **The bot will NOT allow any trade with BALLER tier at $62.49 balance.**

**Reason**: BALLER tier requires a **minimum $100.00 trade size**, but the account only has **$62.49** available.

---

## Detailed Analysis

### Account Status
- **Balance**: $62.49
- **Requested Tier**: BALLER
- **Appropriate Tier**: STARTER (for $50-$99 balances)
- **Tier Mismatch**: ⚠️ YES - Manual override would be required

### BALLER Tier Requirements
- **Capital Range**: $25,000 - $∞
- **Risk Per Trade**: 1.0% - 2.0%
- **Trade Size Range**: **$100.00 - $1,000.00**
- **Max Positions**: 8
- **Description**: Capital deployment

### Why BALLER Tier Fails at $62.49

1. **Tier Minimum Violation**:
   - BALLER tier requires: **$100.00 minimum** trade size
   - Available balance: **$62.49**
   - **Gap**: $37.51 short of minimum
   - **Result**: ❌ VALIDATION FAILS

2. **Capital Requirement Violation**:
   - BALLER tier designed for: **$25,000+** accounts
   - Current balance: **$62.49**
   - **Gap**: $24,937.51 below tier minimum capital
   - **Result**: ⚠️ Severely undercapitalized

3. **Maximum Possible Trade Size**:
   - Even using 100% of balance: **$62.49**
   - Tier requires minimum: **$100.00**
   - **Cannot meet tier requirements**

### Fee Breakdown (If Trade Were Allowed)

Using limit orders (0.4% maker fee):
- Entry Fee: $0.25 (0.40%)
- Spread Cost: $0.13 (0.20%)
- Exit Fee: $0.25 (0.40%)
- **Total Round-Trip**: $0.62 (1.00%)

### Profitability Analysis (Theoretical)

If a $62.49 trade were executed:
- **Breakeven Movement**: 1.00% price movement needed
- **Minimum Profit Target**: 2.00% (to overcome fees + buffer)
- **Minimum Profit Dollars**: $1.25 needed after fees
- **Effective Trade Size**: $62.24 (after entry fee)

---

## What The Bot Will Actually Do

### Scenario 1: BALLER Tier with $62.49 (As Requested)

```python
Balance: $62.49
Tier: BALLER (manual override)
Validation: ❌ FAIL

Reason: "Trade size $62.49 below tier minimum $100.00"
Result: NO TRADE EXECUTED
```

**The bot will block the trade completely.**

### Scenario 2: Appropriate Tier (STARTER) with $62.49

If the account properly uses STARTER tier:

```python
Balance: $62.49
Tier: STARTER (auto-detected)
Suggested Trade Size: $10.00 (tier minimum)
Validation: ✅ PASS (with caveats)
```

**Trade Details**:
- Size: $10.00
- % of Balance: 16.0%
- Risk Level: Within STARTER tier 10-15% range
- Result: ✅ TRADE ALLOWED

---

## Recommendations

### Option 1: Use Proper Tier (RECOMMENDED)
**Switch to STARTER tier** for accounts with $50-$99:
```bash
# In .env file
TRADING_TIER=STARTER
```

**Benefits**:
- Trade size: $10.00 - $25.00 range
- Appropriate risk management for this balance
- Validation will pass
- Can actually execute trades

### Option 2: Fund Account to BALLER Minimum
To properly use BALLER tier:
- **Required Deposit**: $24,937.51
- **New Balance**: $25,000.00
- **Then BALLER tier becomes appropriate**

### Option 3: Wait Until Balance Grows
Natural progression path:
1. **Current**: $62.49 → Use STARTER tier ($10-$25 trades)
2. **At $100**: Upgrade to SAVER tier ($15-$40 trades)
3. **At $250**: Upgrade to INVESTOR tier ($20-$75 trades)
4. **At $1,000**: Upgrade to INCOME tier ($30-$150 trades)
5. **At $5,000**: Upgrade to LIVABLE tier ($50-$300 trades)
6. **At $25,000**: Upgrade to BALLER tier ($100-$1,000 trades) ✅

---

## Technical Calculation Details

### Fee-Aware Position Sizing
For $62.49 balance, the fee-aware calculation suggests:
- Position %: 50.0% (for balances $2-$50)
- Calculated Size: $31.25
- But clamped by tier min/max: $10.00 - $25.00

### Position Sizer Rules
- **Minimum Position**: $2.00 (absolute minimum)
- **Fee-Aware Minimum**: Varies by balance
- **Tier Minimum**: $100.00 (BALLER)
- **Effective Minimum**: Greater of all three

### Validation Rules (BALLER Tier)
1. ✅ Balance >= $2.00 (MIN_BALANCE_TO_TRADE)
2. ❌ Trade size >= $100.00 (Tier minimum) **← FAILS HERE**
3. ❌ Trade size <= $1,000.00 (Tier maximum)
4. ❌ Trade size represents 1-2% of balance (Risk limits)

**At $62.49, none of the BALLER tier requirements can be met.**

---

## Code References

### Tier Configuration
Source: `bot/tier_config.py`
```python
TradingTier.BALLER: TierConfig(
    name="BALLER",
    capital_min=25000.0,
    capital_max=float('inf'),
    risk_per_trade_pct=(1.0, 2.0),
    trade_size_min=100.0,    # ← This is the blocker
    trade_size_max=1000.0,
    max_positions=8,
    description="Capital deployment",
    min_visible_size=100.0
)
```

### Position Sizer
Source: `bot/position_sizer.py`
```python
MIN_POSITION_USD = 2.0  # Absolute minimum
```

### Fee Configuration
Source: `bot/fee_aware_config.py`
```python
COINBASE_LIMIT_ORDER_FEE = 0.004   # 0.4% maker
COINBASE_MARKET_ORDER_FEE = 0.006  # 0.6% taker
COINBASE_SPREAD_COST = 0.002       # 0.2% spread
```

---

## Conclusion

**FINAL ANSWER**:

**The exact maximum dollar amount the bot will ATTEMPT with BALLER tier at $62.49 is: $62.49**

However, this will **IMMEDIATELY FAIL VALIDATION** because:
1. The $62.49 is below the BALLER tier's $100.00 minimum trade size
2. The account is severely undercapitalized for BALLER tier ($25,000 minimum capital)
3. Validation error: "Trade size $62.49 below tier minimum $100.00"

**Result**: ❌ **NO TRADE WILL BE EXECUTED**

The bot calculates $62.49 as the maximum it could use (entire balance), but immediately rejects it during validation.

**To trade with this balance**, you must either:
- Switch to STARTER tier (allows $10-$25 trades) ✅ RECOMMENDED
- Or deposit $24,937.51 more to reach BALLER tier's minimum capital requirement

---

## Testing Commands

To verify these calculations yourself:

```bash
# Test BALLER tier at $62.49 (will fail)
python calculate_safe_trade_size.py --balance 62.49 --tier BALLER

# Test appropriate tier at $62.49 (will succeed)
python calculate_safe_trade_size.py --balance 62.49

# Test BALLER tier at proper capital level
python calculate_safe_trade_size.py --balance 25000 --tier BALLER
```

---

**Report Generated**: January 22, 2026
**Tool**: `calculate_safe_trade_size.py`
**Bot Version**: NIJA v7.1
**Status**: ✅ Calculation Complete
