# Capital Capacity Calculator - User Guide

## Overview

The NIJA Capital Capacity Calculator provides comprehensive analysis of your trading capital, showing exactly how much you can deploy and what your maximum position size should be for any account.

## Key Metrics

### 1. Total Equity
Your complete account value including:
- Available cash
- Value of open positions
- Unrealized profit/loss

**Formula:** `Total Equity = Available Cash + Position Value`

### 2. Deployable Capital
The amount of capital available for new positions, accounting for:
- Minimum reserve requirements (default 10%)
- Capital already deployed in open positions

**Formula:** `Deployable Capital = (Total Equity × (1 - Reserve%)) - Current Positions`

### 3. Maximum Position Size
The largest single position you can open, constrained by:
- Maximum position percentage (default 15% of total equity)
- Available deployable capital
- Available cash

**Formula:** `Max Position = min(Total Equity × Max%, Deployable Capital, Available Cash)`

## Usage

### Single Account Analysis

Calculate capital capacity for one account:

```bash
# Account with $10,000 balance and $2,000 in open positions
python calculate_capital_capacity.py --balance 10000 --positions 2000

# Small account with no positions
python calculate_capital_capacity.py --balance 500

# Custom reserve (15%) and max position (20%)
python calculate_capital_capacity.py --balance 10000 --positions 2000 --reserve-pct 15 --max-position-pct 20
```

**Parameters:**
- `--balance`: Account balance (total cash available)
- `--positions`: Total value of open positions (default: 0)
- `--unrealized-pnl`: Unrealized P/L from positions (default: 0)
- `--reserve-pct`: Minimum reserve % to maintain (default: 10)
- `--max-position-pct`: Maximum position size as % of equity (default: 15)
- `--account-name`: Account name for display

### All Accounts Analysis

Calculate for master account + all user accounts:

```bash
# Display all accounts from portfolio manager
python calculate_all_accounts_capital.py

# Run with simulated example accounts
python calculate_all_accounts_capital.py --simulate

# Custom settings for all accounts
python calculate_all_accounts_capital.py --simulate --max-position-pct 20 --reserve-pct 15
```

**Features:**
- Shows individual account breakdowns
- Aggregate summary across all accounts
- Portfolio-wide capacity distribution
- Combined deployable capital

## Example Output

### Single Account

```
================================================================================
CAPITAL CAPACITY ANALYSIS - Account
================================================================================

💰 ACCOUNT BALANCES:
   Total Equity: $12,000.00
   Available Cash: $10,000.00
   Position Value: $2,000.00
   Unrealized P/L: $+0.00

📊 POSITION METRICS:
   Open Positions: 1
   Cash Utilization: 16.7%

🎯 CAPITAL DEPLOYMENT:
   Min Reserve Required: 10.0% ($1,200.00)
   Max Deployable Total: $10,800.00
   Currently Deployed: $2,000.00
   ──────────────────────────────────────
   EFFECTIVE DEPLOYABLE CAPITAL: $8,800.00

📏 POSITION SIZING:
   Max Position %: 15.0%
   ──────────────────────────────────────
   MAX POSITION SIZE: $1,800.00

📈 CAPACITY METRICS:
   Deployment Capacity Used: 18.5%
   Remaining Capacity: $8,800.00

💡 RECOMMENDATIONS:
   ✅ HEALTHY CAPACITY: Can open new positions up to $1,800.00
   💼 LOW UTILIZATION: 16.7% of equity is in positions
   → Significant capital available for deployment
```

### All Accounts

```
================================================================================
NIJA ALL ACCOUNTS CAPITAL CAPACITY CALCULATOR
================================================================================

🎯 Master Account (Master)
──────────────────────────────────────────────────────────────────────────────
  Total Equity:        $   24,600.00
  Available Cash:      $   20,000.00
  Position Value:      $    4,600.00
  Open Positions:                 1
  Utilization:                18.7%
  ────────────────────────────────────────────────
  💰 Deployable Capital: $ 17,540.00
  📏 Max Position Size:  $  3,690.00

================================================================================
AGGREGATE SUMMARY - ALL 4 ACCOUNTS
================================================================================

💼 PORTFOLIO TOTALS:
   Total Equity (All Accounts):     $      42,770.00
   Total Available Cash:             $      27,500.00
   Total Position Value:             $      15,270.00
   Total Open Positions:                           4
   Average Utilization:                        35.5%

🎯 AGGREGATE CAPACITY:
   Combined Deployable Capital:      $      23,223.00
   Combined Max Position Size:       $       6,410.50
```

## Programmatic Usage

### In Python Code

```python
from bot.portfolio_state import PortfolioState

# Create portfolio state
portfolio = PortfolioState(available_cash=10000.0, min_reserve_pct=0.10)

# Add positions
portfolio.add_position("BTC-USD", 0.1, 45000, 46000)

# Calculate deployable capital
deployable = portfolio.calculate_deployable_capital()
print(f"Deployable: ${deployable:.2f}")

# Calculate max position size
max_position = portfolio.calculate_max_position_size(max_position_pct=0.15)
print(f"Max Position: ${max_position:.2f}")

# Get full breakdown
breakdown = portfolio.get_capital_breakdown()
print(f"Total Equity: ${breakdown['total_equity']:.2f}")
print(f"Deployable: ${breakdown['deployable_capital']:.2f}")
print(f"Max Position: ${breakdown['max_position_size']:.2f}")
```

### With Portfolio Manager

```python
from bot.portfolio_state import get_portfolio_manager

# Get portfolio manager
mgr = get_portfolio_manager()

# Initialize master portfolio
master = mgr.initialize_master_portfolio(available_cash=25000.0)
master.add_position("BTC-USD", 0.2, 45000, 46000)

# Get capital breakdown
breakdown = master.get_capital_breakdown(
    max_position_pct=0.15,
    min_reserve_pct=0.10
)

print(f"Master Account:")
print(f"  Total Equity: ${breakdown['total_equity']:.2f}")
print(f"  Deployable: ${breakdown['deployable_capital']:.2f}")
print(f"  Max Position: ${breakdown['max_position_size']:.2f}")
```

## Understanding the Calculations

### Example Scenario

**Account State:**
- Available Cash: $10,000
- Open Position: $2,000
- Total Equity: $12,000

**With 10% Reserve and 15% Max Position:**

1. **Total Equity** = $12,000 (cash + positions)

2. **Min Reserve** = $12,000 × 10% = $1,200
   - Must always keep this much available

3. **Max Deployable** = $12,000 - $1,200 = $10,800
   - Maximum that can ever be in positions

4. **Current Deployed** = $2,000
   - Already have this much in positions

5. **Deployable Capital** = $10,800 - $2,000 = $8,800
   - Can still deploy this much

6. **Max Position by %** = $12,000 × 15% = $1,800
   - Single position limit based on equity

7. **Max Position Size** = min($1,800, $8,800, $10,000) = $1,800
   - Limited by the percentage rule

## Best Practices

### Reserve Requirements

**Conservative (15-20%):**
- Good for volatile markets
- Ensures cash for emergencies
- Reduces risk of being fully deployed

**Moderate (10-15%):**
- Standard for most traders
- Balance between safety and efficiency
- Default NIJA setting

**Aggressive (5-10%):**
- For experienced traders
- Requires active management
- Higher capital efficiency

### Position Sizing

**Conservative (10-12%):**
- Safer risk management
- More diversification possible
- Good for larger accounts

**Moderate (15-20%):**
- Standard position sizing
- Balance of risk and reward
- Default NIJA setting

**Aggressive (20-25%):**
- Higher concentration risk
- Requires strong conviction
- Better for smaller accounts

## Integration with Trading Bot

The capital capacity calculations are integrated into:

1. **Portfolio State Management**
   - Real-time tracking of deployable capital
   - Automatic calculation with each balance update

2. **Risk Manager**
   - Position sizing uses deployable capital
   - Respects maximum position limits

3. **Trade Execution**
   - Validates against deployable capital
   - Prevents over-deployment

4. **User Account Management**
   - Each user has independent capacity calculation
   - Master account controls overall strategy

## Troubleshooting

### "No deployable capital available"

**Causes:**
- Too many open positions
- Positions too large relative to equity
- Reserve requirement too high

**Solutions:**
- Close some positions
- Reduce reserve percentage
- Add more capital

### "Max position size too small"

**Causes:**
- Small account size
- High reserve requirements
- Many open positions

**Solutions:**
- Increase max position percentage
- Reduce reserve percentage
- Close positions to free capital
- Add more capital

### "Negative deployable capital"

This should never happen, but if it does:
- Check for calculation errors
- Verify position values are current
- Ensure reserve percentage is reasonable (0-50%)

## FAQs

**Q: Why use total equity instead of just cash?**
A: Total equity gives a complete picture of your account value. Cash-only calculations ignore the capital you have in positions, leading to over-trading.

**Q: What's the right reserve percentage?**
A: Most traders use 10-15%. Higher is safer but less capital efficient. Lower is more aggressive.

**Q: Can I set different reserves per account?**
A: Yes, each PortfolioState can have its own `min_reserve_pct`.

**Q: How often should I recalculate?**
A: Automatically done with each balance update. Manual checks useful before major trades.

**Q: What if I want to deploy 100% of capital?**
A: Set `min_reserve_pct=0.0`, but this is risky and not recommended.

## See Also

- `TRADE_SIZE_TUNING_GUIDE.md` - Position sizing strategies
- `RISK_PROFILES_GUIDE.md` - Risk management guidelines
- `USER_BALANCE_GUIDE.md` - Account balance management
- `portfolio_state.py` - Source code documentation
