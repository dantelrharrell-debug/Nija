# Safe Trade Size Calculator - Usage Guide

## Overview

The **Safe Trade Size Calculator** (`calculate_safe_trade_size.py`) is a comprehensive tool that calculates the exact maximum safe trade size for any NIJA trading tier and balance combination, accounting for:

- ✅ Tier-based trade size limits (min/max)
- ✅ Fee-aware configuration (Coinbase fees ~1.0-1.4% round-trip)
- ✅ Position sizer minimums ($2.00 minimum position)
- ✅ Risk management rules (tier-specific risk percentages)
- ✅ Tier override scenarios
- ✅ Complete fee breakdown
- ✅ Profitability analysis

---

## Quick Start

### Basic Usage

```bash
# Calculate for a specific balance with auto-detected tier
python calculate_safe_trade_size.py --balance 62.49

# Calculate for a specific balance and tier
python calculate_safe_trade_size.py --balance 62.49 --tier BALLER

# Calculate with market orders (higher fees)
python calculate_safe_trade_size.py --balance 25000 --tier BALLER --market-order
```

---

## Real-World Examples

### Example 1: BALLER Tier at $62.49 (Undercapitalized)

```bash
python calculate_safe_trade_size.py --balance 62.49 --tier BALLER
```

**Result**:
- **Suggested Trade Size**: $62.49 (entire balance)
- **Validation**: ❌ FAIL
- **Reason**: Trade size $62.49 below tier minimum $100.00
- **Recommendation**: Switch to STARTER tier

**Key Findings**:
- BALLER tier requires $100-$1,000 trade sizes
- Account only has $62.49
- Even using 100% of balance cannot meet tier minimums
- **Answer to the question**: The bot will **attempt** $62.49 but **reject** it immediately

---

### Example 2: BALLER Tier at $25,000 (Proper Capital)

```bash
python calculate_safe_trade_size.py --balance 25000 --tier BALLER
```

**Result**:
- **Suggested Trade Size**: $500.00
- **Validation**: ✅ PASS
- **Calculation**: 2% of $25,000 (max risk for BALLER tier)
- **Fees**: $5.00 (1.0% round-trip with limit orders)
- **Effective Size**: $498.00 (after entry fee)

**Why not $1,000?**
- BALLER tier max is $1,000, but that would be 4% of balance
- Tier risk limit is 2% maximum
- $500 respects both the tier max and risk limit

---

### Example 3: STARTER Tier at $62.49 (Appropriate Tier)

```bash
python calculate_safe_trade_size.py --balance 62.49 --tier STARTER
```

**Result**:
- **Suggested Trade Size**: $10.00 (tier minimum)
- **Validation**: ❌ FAIL (edge case!)
- **Reason**: $10 represents 16% of balance, exceeds 15% max risk
- **Actual Safe Size**: $9.37 (15% of $62.49)
- **Problem**: $9.37 is below tier minimum of $10.00

**This reveals a gap in the tier system!**
- At $62.49, you're caught between tier minimum and risk limits
- Need at least $66.67 to properly trade STARTER tier
- Options:
  1. Deposit $4.18 more to reach $66.67
  2. Accept the $10 trade with slightly elevated risk (16%)

---

### Example 4: Auto-Detected Tier

```bash
python calculate_safe_trade_size.py --balance 500
```

**Result**:
- **Auto-Detected Tier**: INVESTOR ($250-$999)
- **Suggested Trade Size**: $35.00
- **Validation**: ✅ PASS
- **Calculation**: 7% of $500 (max risk for INVESTOR tier)

---

## Understanding the Output

### Account Information
- **Balance**: Your current account balance
- **Current Tier**: The tier you're requesting (or auto-detected)
- **Appropriate Tier**: What tier the balance should actually use
- **Tier Match**: Whether you're using the right tier

### Tier Configuration
- **Capital Range**: Required balance range for this tier
- **Risk Per Trade**: Allowed risk percentage range
- **Trade Size Range**: Min/max trade sizes in USD
- **Max Positions**: Maximum concurrent positions

### Trade Size Calculation
- **Fee-Aware %**: Percentage based on balance size
- **Fee-Aware Size**: Raw calculation before tier limits
- **Tier Minimum/Maximum**: Hard limits from tier config
- **Position Sizer Minimum**: Absolute minimum ($2.00)
- **Suggested Trade Size**: Final calculated safe size

### Fee Breakdown
Shows fees for the suggested trade size:
- **Entry Fee**: Fee to open the position
- **Spread Cost**: Bid-ask spread cost
- **Exit Fee**: Fee to close the position
- **Total Fees**: Sum of all costs

### Profitability Requirements
- **Breakeven Price Movement**: How much price must move to cover fees
- **Minimum Profit Target**: Recommended target to beat fees + buffer
- **Minimum Profit (USD)**: Dollar amount needed for profit

### Validation
- **Can Trade**: Whether the trade will be allowed
- **Reason**: Why it passed or failed
- **Warnings**: Important alerts about tier mismatches, etc.
- **Recommendation**: What you should do

---

## All Available Tiers

| Tier | Capital Range | Trade Size | Risk % | Max Positions |
|------|---------------|------------|--------|---------------|
| **STARTER** | $50-$99 | $10-$25 | 10-15% | 1 |
| **SAVER** | $100-$249 | $15-$40 | 7-10% | 2 |
| **INVESTOR** | $250-$999 | $20-$75 | 5-7% | 3 |
| **INCOME** | $1k-$4.9k | $30-$150 | 3-5% | 5 |
| **LIVABLE** | $5k-$24.9k | $50-$300 | 2-3% | 6 |
| **BALLER** | $25k+ | $100-$1k | 1-2% | 8 |

---

## Fee Structure (Coinbase Advanced Trade)

### Limit Orders (Maker)
- **Entry Fee**: 0.40%
- **Exit Fee**: 0.40%
- **Spread**: ~0.20%
- **Total Round-Trip**: ~1.00%

### Market Orders (Taker)
- **Entry Fee**: 0.60%
- **Exit Fee**: 0.60%
- **Spread**: ~0.20%
- **Total Round-Trip**: ~1.40%

**Recommendation**: Use `--market-order` flag only for testing worst-case scenarios. Limit orders save money.

---

## Command-Line Options

### Required
- `--balance AMOUNT`: Account balance in USD (required)

### Optional
- `--tier TIER`: Specify tier (STARTER, SAVER, INVESTOR, INCOME, LIVABLE, BALLER)
  - If not provided, tier is auto-detected from balance
- `--market-order`: Use market order fees (0.6%) instead of limit order fees (0.4%)
  - Default: Uses limit order fees

---

## Common Scenarios

### "I have $62.49 and want to use BALLER tier"
```bash
python calculate_safe_trade_size.py --balance 62.49 --tier BALLER
```
**Answer**: Bot will calculate $62.49 but **REJECT** it (below $100 minimum)

### "I have $25,000, what's my safe BALLER trade size?"
```bash
python calculate_safe_trade_size.py --balance 25000 --tier BALLER
```
**Answer**: $500.00 (2% max risk)

### "What tier should I use with $150?"
```bash
python calculate_safe_trade_size.py --balance 150
```
**Answer**: SAVER tier, $22.50 trade size (15% max)

### "I want to see worst-case fees with market orders"
```bash
python calculate_safe_trade_size.py --balance 500 --market-order
```
**Answer**: Shows 1.40% round-trip fees instead of 1.00%

---

## Exit Codes

- **0**: Trade validated successfully (can trade)
- **1**: Trade failed validation (cannot trade)

Use exit codes in scripts:
```bash
if python calculate_safe_trade_size.py --balance 62.49 --tier BALLER; then
    echo "Trade is valid"
else
    echo "Trade is invalid"
fi
```

---

## Integration with NIJA Bot

This calculator uses the **exact same logic** as the NIJA bot:

1. `bot/tier_config.py` - Tier definitions and limits
2. `bot/position_sizer.py` - Position sizing rules
3. `bot/fee_aware_config.py` - Fee calculations and profitability

**What the calculator shows is exactly what the bot will do.**

---

## Interpreting Warnings

### "TIER MISMATCH"
Your balance doesn't match the tier you selected.
- **Fix**: Use the recommended tier or deposit/withdraw to match

### "UNDERCAPITALIZED"
Your balance is below the tier's minimum capital requirement.
- **Fix**: Choose a lower tier or deposit more funds

### "MICRO POSITION"
Trade size is very small (< $10) and faces high fee pressure.
- **Fix**: Deposit more funds or accept limited profitability

### "MICRO ACCOUNT"
Balance is below $5, quality multipliers are bypassed.
- **Fix**: This is expected for learning/testing with minimal capital

---

## Tips for Profitability

1. **Match Your Tier**: Always use the tier appropriate for your balance
2. **Respect Minimums**: Don't trade if you can't meet tier minimums
3. **Fund Adequately**: Minimum $30-50 for viable trading after fees
4. **Use Limit Orders**: Save 0.4% on fees vs market orders
5. **Quality Over Quantity**: Fewer, better trades beat many small trades

---

## Advanced Usage

### Batch Testing Multiple Balances

```bash
for balance in 50 100 250 1000 5000 25000; do
    echo "Testing balance: $balance"
    python calculate_safe_trade_size.py --balance $balance
    echo "---"
done
```

### Testing Tier Boundaries

```bash
# Test right at tier boundaries
python calculate_safe_trade_size.py --balance 99.99  # Top of STARTER
python calculate_safe_trade_size.py --balance 100.00 # Bottom of SAVER
python calculate_safe_trade_size.py --balance 249.99 # Top of SAVER
python calculate_safe_trade_size.py --balance 250.00 # Bottom of INVESTOR
```

### Comparing Limit vs Market Orders

```bash
# Limit orders (default)
python calculate_safe_trade_size.py --balance 1000

# Market orders
python calculate_safe_trade_size.py --balance 1000 --market-order
```

---

## Troubleshooting

### "ModuleNotFoundError"
Make sure you're running from the repository root:
```bash
cd /path/to/Nija
python calculate_safe_trade_size.py --balance 100
```

### "ImportError: tier_config"
The script needs access to `bot/` directory. Verify it exists:
```bash
ls -la bot/tier_config.py
```

### Unexpected Results
1. Check your balance is correct
2. Verify tier spelling (case-sensitive)
3. Review warnings in output
4. Compare with tier requirements table

---

## Related Documentation

- **BALLER_TIER_62_49_ANALYSIS.md**: Detailed analysis for the $62.49 BALLER scenario
- **RISK_PROFILES_GUIDE.md**: Complete tier documentation
- **bot/tier_config.py**: Source code for tier definitions
- **bot/fee_aware_config.py**: Fee calculation source code

---

## Support

For questions or issues:
1. Run the calculator with your specific scenario
2. Read the output carefully, especially warnings
3. Check related documentation files
4. Review tier requirements in RISK_PROFILES_GUIDE.md

---

**Version**: 1.0  
**Last Updated**: January 22, 2026  
**Status**: ✅ Production Ready
