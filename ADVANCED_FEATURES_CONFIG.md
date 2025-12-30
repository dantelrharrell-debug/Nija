# Advanced Trading Features Configuration

## Overview

This document covers configuration options for the advanced trading features introduced in the progressive profit target implementation:

1. Progressive Daily Profit Targets
2. Exchange-Specific Risk Profiles
3. Multi-Exchange Capital Allocation

## Environment Variables

### Core Settings

```bash
# Initial capital for the bot (default: 100)
# This is used for initial position sizing calculations
# Will be updated automatically when brokers connect
export INITIAL_CAPITAL=100

# Capital allocation strategy (default: conservative)
# Options: conservative, risk_adjusted, equal_weight
export ALLOCATION_STRATEGY=conservative

# Minimum balance required to trade (default: 2.0)
# Trading is disabled if balance falls below this
export MIN_BALANCE_TO_TRADE_USD=2.0

# Maximum positions allowed (default: 8)
# Prevents over-leveraging
export MAX_POSITIONS_ALLOWED=8

# Minimum position size in USD (default: 1.0)
# Prevents dust trades
export MIN_POSITION_SIZE_USD=1.0
```

### Advanced Settings

```bash
# Enable exchange-specific risk profiles (default: false)
# When enabled, risk parameters are optimized per exchange
export USE_EXCHANGE_PROFILES=true

# Progressive targets starting level (default: 25)
# The initial daily profit target in USD
export PROGRESSIVE_TARGET_START=25

# Progressive targets increment (default: 25)
# How much to increase target at each level
export PROGRESSIVE_TARGET_INCREMENT=25

# Progressive targets goal (default: 1000)
# The final daily profit target
export PROGRESSIVE_TARGET_GOAL=1000
```

## Allocation Strategies

### Conservative (Default)

Best for: Small accounts, risk-averse trading, stable growth

**Capital Distribution:**
- Coinbase: 70%
- OKX: 30%

**Characteristics:**
- Prioritizes Coinbase for reliability
- Uses OKX for lower fees on high-conviction trades
- Lower drawdown potential
- Moderate profit potential

**Recommended for:**
- Accounts under $500
- New traders
- Conservative risk tolerance

### Risk-Adjusted

Best for: Medium accounts, balanced approach

**Capital Distribution:**
- Dynamically allocated based on:
  - Exchange risk scores
  - Recent performance
  - Fee structures
  - Volatility levels

**Characteristics:**
- Adapts to market conditions
- Balances risk and reward
- May shift allocation over time
- Moderate complexity

**Recommended for:**
- Accounts $500-$5000
- Experienced traders
- Moderate risk tolerance

### Equal-Weight

Best for: Large accounts, maximum diversification

**Capital Distribution:**
- Equal split across all connected exchanges
- Automatically rebalances

**Characteristics:**
- Maximum diversification
- Smooths out exchange-specific issues
- Requires more management overhead
- Higher transaction costs (more exchanges)

**Recommended for:**
- Accounts over $5000
- Advanced traders
- Lower correlation to single exchange

## Exchange-Specific Risk Profiles

When enabled (`USE_EXCHANGE_PROFILES=true`), each exchange has optimized parameters:

### Coinbase Advanced Trade

**Fee Structure:**
- Maker: 0.4%
- Taker: 0.6%
- Round-trip: 1.4%

**Risk Parameters:**
- Min position: $10
- Recommended position: 5%
- Max position: 15%
- Stop-loss: 0.8-2.0%
- Take-profit targets: 2.0%, 3.5%, 5.0%
- Min profit target: 2.0% (to cover fees)
- Max trades/day: 30
- Risk score: 3/10 (conservative)

**Best for:**
- Primary broker for US traders
- Reliable execution
- Regulatory compliance
- Higher capital accounts

### OKX Exchange

**Fee Structure:**
- Maker: 0.08%
- Taker: 0.10%
- Round-trip: 0.3%

**Risk Parameters:**
- Min position: $5
- Recommended position: 7%
- Max position: 20%
- Stop-loss: 0.5-1.5%
- Take-profit targets: 1.0%, 2.0%, 3.5%
- Min profit target: 0.5%
- Max trades/day: 50
- Risk score: 5/10 (moderate)

**Best for:**
- High-frequency trading
- Lower fees
- More aggressive strategies
- Medium to large accounts

### Kraken Pro

**Fee Structure:**
- Maker: 0.16%
- Taker: 0.26%
- Round-trip: 0.67%

**Risk Parameters:**
- Min position: $10
- Recommended position: 5%
- Max position: 15%
- Stop-loss: 0.6-1.8%
- Take-profit targets: 1.5%, 2.5%, 4.0%
- Min profit target: 1.0%
- Max trades/day: 40
- Risk score: 4/10 (balanced)

**Best for:**
- European traders
- Good fee structure
- Reliable platform
- All account sizes

### Binance

**Fee Structure:**
- Maker: 0.10%
- Taker: 0.10%
- Round-trip: 0.28%

**Risk Parameters:**
- Min position: $5
- Recommended position: 8%
- Max position: 25%
- Stop-loss: 0.5-1.5%
- Take-profit targets: 1.0%, 2.0%, 3.5%
- Min profit target: 0.5%
- Max trades/day: 60
- Risk score: 6/10 (aggressive)

**Best for:**
- Highest liquidity
- Lowest fees
- Aggressive trading
- Large accounts

### Alpaca (Stocks)

**Fee Structure:**
- Zero fees (commission-free)

**Risk Parameters:**
- Min position: $1
- Recommended position: 3%
- Max position: 10%
- Stop-loss: 0.5-2.0%
- Take-profit targets: 1.0%, 2.0%, 3.0%
- Min profit target: 0.5%
- Max trades/day: 25
- Risk score: 2/10 (very conservative)

**Best for:**
- Stock trading
- No fee concerns
- Regulated US markets
- Day trading stocks

## Progressive Target Levels

The system has 40 levels from $25 to $1000:

| Level | Daily Target | Position Multiplier | Recommended Capital |
|-------|-------------|---------------------|-------------------|
| 1     | $25         | 1.00x               | $50+              |
| 5     | $125        | 1.10x               | $250+             |
| 10    | $250        | 1.25x               | $500+             |
| 15    | $375        | 1.33x               | $750+             |
| 20    | $500        | 1.40x               | $1,000+           |
| 25    | $625        | 1.44x               | $1,250+           |
| 30    | $750        | 1.47x               | $1,500+           |
| 35    | $875        | 1.49x               | $1,750+           |
| 40    | $1000       | 1.50x               | $2,000+           |

**Position Multiplier Formula:**
```
multiplier = 1.0 + (level / 80)
capped at 1.5x maximum
```

## Capital Allocation Rules

### Rebalancing Triggers

Automatic rebalancing occurs when:
1. **Drift > 10%**: Allocation drifts more than 10% from target
2. **Daily Check**: At end of each trading day
3. **Performance Issues**: Exchange underperforming significantly
4. **Manual Trigger**: Via `capital_allocator.trigger_rebalancing()`

### Maximum Exposure Limits

Per-exchange exposure is limited to:
- Conservative: 40% total portfolio
- Risk-adjusted: 50% total portfolio
- Equal-weight: 60% total portfolio

These limits prevent over-concentration on any single exchange.

### Minimum Position Requirements

Each exchange has minimum position requirements:
- Positions below minimum are rejected
- Prevents unprofitable dust trades
- Accounts for exchange-specific fees

## Risk Management Integration

### Position Sizing

Final position size considers:
1. Base position percentage (from strategy)
2. Signal strength (0-1 confidence)
3. Progressive target multiplier
4. Exchange-specific constraints
5. Available capital on exchange
6. Current exposure limits

**Formula:**
```
adjusted_pct = base_pct × signal_strength × target_multiplier
position_size = min(
    adjusted_pct × allocated_capital,
    max_position_size_for_exchange
)
```

### Stop-Loss Calculation

Stop-loss is adjusted for:
1. Exchange volatility characteristics
2. Fee structure (wider stops for high-fee exchanges)
3. Trading pair characteristics
4. Recent volatility

### Take-Profit Targets

Three-tiered profit targets optimized per exchange:
- **TP1**: Conservative target (cover fees + small profit)
- **TP2**: Moderate target (reasonable profit)
- **TP3**: Aggressive target (maximum expected profit)

All targets adjusted to account for fees.

## Data Persistence

Configuration and state are saved in:

```
data/
  ├── progressive_targets.json      # Target progression history
  ├── capital_allocation.json       # Current allocation state
  └── trade_history.jsonl          # Trade records
```

These files:
- Persist across restarts
- Are automatically backed up
- Can be manually edited (with caution)
- Use human-readable JSON format

## Configuration Validation

The system validates:
- ✅ Capital > 0
- ✅ Allocation strategy is valid
- ✅ Exchange profiles exist
- ✅ Position limits are reasonable
- ✅ Fee structures are current

Invalid configuration raises `ValueError` with descriptive error message.

## Example Configurations

### Small Account ($100)

```bash
export INITIAL_CAPITAL=100
export ALLOCATION_STRATEGY=conservative
export MIN_POSITION_SIZE_USD=1.0
export USE_EXCHANGE_PROFILES=true
export PROGRESSIVE_TARGET_START=25
```

### Medium Account ($1000)

```bash
export INITIAL_CAPITAL=1000
export ALLOCATION_STRATEGY=risk_adjusted
export MIN_POSITION_SIZE_USD=5.0
export USE_EXCHANGE_PROFILES=true
export PROGRESSIVE_TARGET_START=50
```

### Large Account ($10000)

```bash
export INITIAL_CAPITAL=10000
export ALLOCATION_STRATEGY=equal_weight
export MIN_POSITION_SIZE_USD=10.0
export USE_EXCHANGE_PROFILES=true
export PROGRESSIVE_TARGET_START=100
```

## Monitoring and Logging

All configuration changes are logged with:
- Timestamp
- Old value → New value
- Reason for change
- Impact on trading

Check logs for messages tagged:
- `nija.advanced_integration` - Main integration logs
- `nija.progressive_targets` - Target progression logs
- `nija.exchange_risk` - Exchange profile logs
- `nija.capital_allocation` - Allocation logs

## Best Practices

1. **Start Conservative**: Use conservative allocation for new accounts
2. **Monitor Closely**: Watch first few trades carefully
3. **Adjust Gradually**: Change one setting at a time
4. **Backtest First**: Test configuration changes in paper trading
5. **Document Changes**: Keep notes on what works
6. **Review Regularly**: Reassess monthly as account grows

## Troubleshooting

### High Fees Eating Profits

- Increase `MIN_POSITION_SIZE_USD`
- Use exchanges with lower fees (OKX, Binance)
- Enable `USE_EXCHANGE_PROFILES` for fee-aware targeting

### Positions Too Small

- Check `INITIAL_CAPITAL` is set correctly
- Verify capital allocation is updating
- Review exchange-specific minimums

### Not Hitting Targets

- Lower `PROGRESSIVE_TARGET_START` if too aggressive
- Review fee impact on profitability
- Check if stop-losses are too tight
- Verify signal quality

### Allocation Issues

- Check `data/capital_allocation.json` for corruption
- Verify all exchanges are connected
- Review allocation strategy fit for account size
- Check for rebalancing errors in logs

## Summary

Proper configuration of advanced trading features requires:
- Understanding your account size and risk tolerance
- Choosing appropriate allocation strategy
- Setting realistic progressive targets
- Enabling exchange-specific optimizations
- Regular monitoring and adjustment

Start with recommended settings for your account size, monitor performance, and adjust gradually based on results.
