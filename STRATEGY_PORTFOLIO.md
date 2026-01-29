# NIJA Strategy Portfolio Manager

## Overview

The Strategy Portfolio Manager transforms NIJA into a multi-strategy fund engine. It coordinates multiple uncorrelated trading strategies, performs portfolio optimization, and implements regime-based strategy switching.

This is the foundation for building a diversified multi-strategy trading fund.

## Features

### Core Capabilities

1. **Multi-Strategy Coordination**
   - Run multiple strategies simultaneously
   - Independent strategy tracking
   - Unified capital management

2. **Correlation Analysis**
   - Calculate strategy correlation matrix
   - Identify uncorrelated strategies
   - Diversification scoring

3. **Portfolio Optimization**
   - Dynamic capital allocation
   - Risk-adjusted weighting
   - Regime-based allocation

4. **Regime-Based Switching**
   - Automatic strategy selection
   - Market regime detection
   - Adaptive allocation

5. **Strategy Performance Tracking**
   - Individual strategy metrics
   - Comparative analysis
   - Attribution reporting

## Components

### 1. Strategy Portfolio Manager (`bot/strategy_portfolio_manager.py`)

Main orchestrator for multi-strategy operations.

**Key Classes:**
- `TradingStrategy` - Strategy type enum
- `MarketRegime` - Market regime classification
- `StrategyConfig` - Strategy configuration
- `StrategyPerformance` - Performance tracking
- `PortfolioAllocation` - Capital allocation
- `StrategyPortfolioManager` - Main manager class

### 2. Available Strategies

#### APEX_RSI (Main Strategy)
- Dual RSI indicators (RSI_9 + RSI_14)
- Works in most market regimes
- Default allocation: 30-70%

#### TREND_FOLLOWING
- Momentum-based strategy
- Best in strong trends
- Higher risk multiplier: 1.2x

#### MEAN_REVERSION
- Counter-trend strategy
- Best in ranging markets
- Lower risk multiplier: 0.8x

#### BREAKOUT
- Volatility expansion strategy
- Trades breakouts from ranges

#### VOLATILITY_EXPANSION
- Trades increasing volatility
- Crisis/volatile regime specialist

#### PAIRS_TRADING
- Statistical arbitrage
- Market-neutral approach

### 3. Market Regimes

#### BULL_TRENDING
- Strong uptrend
- High momentum
- Favor: APEX_RSI, TREND_FOLLOWING

#### BEAR_TRENDING
- Strong downtrend
- Favor: TREND_FOLLOWING (short bias)

#### RANGING
- Sideways movement
- Low volatility
- Favor: MEAN_REVERSION, APEX_RSI

#### VOLATILE
- High volatility
- Choppy markets
- Favor: APEX_RSI, VOLATILITY_EXPANSION

#### CRISIS
- Extreme volatility
- Risk-off environment
- Reduce all allocations

## Usage

### Basic Setup

```python
from bot.strategy_portfolio_manager import (
    StrategyPortfolioManager,
    get_portfolio_manager,
    MarketRegime
)

# Initialize portfolio manager
portfolio = get_portfolio_manager(total_capital=100000.0)

# Update market regime
portfolio.update_market_regime(MarketRegime.BULL_TRENDING)

# Optimize allocation
allocation = portfolio.optimize_allocation()

print("Current Allocation:")
for strategy, pct in allocation.allocations.items():
    print(f"  {strategy}: {pct:.1f}%")
```

### Registering Custom Strategy

```python
from bot.strategy_portfolio_manager import StrategyConfig, TradingStrategy

# Define custom strategy
custom_strategy = StrategyConfig(
    name="CUSTOM_MOMENTUM",
    strategy_type=TradingStrategy.TREND_FOLLOWING,
    enabled=True,
    min_allocation_pct=10.0,
    max_allocation_pct=40.0,
    preferred_regimes=[
        MarketRegime.BULL_TRENDING,
        MarketRegime.VOLATILE
    ],
    risk_multiplier=1.1
)

# Register strategy
portfolio.register_strategy(custom_strategy)
```

### Getting Strategy Capital

```python
# Get allocated capital for a strategy
apex_capital = portfolio.get_strategy_capital("APEX_RSI")
trend_capital = portfolio.get_strategy_capital("TREND_FOLLOWING")

print(f"APEX_RSI Capital: ${apex_capital:,.2f}")
print(f"TREND_FOLLOWING Capital: ${trend_capital:,.2f}")
```

### Updating Strategy Performance

```python
# Record trade result for a strategy
trade_result = {
    'pnl': 250.0,
    'return_pct': 2.5
}

portfolio.update_strategy_performance(
    strategy_name="APEX_RSI",
    trade_result=trade_result
)
```

### Correlation Analysis

```python
# Calculate correlation matrix
correlation_matrix = portfolio.calculate_correlation_matrix()

# Get diversification score
diversification_score = portfolio.get_diversification_score()

print(f"Portfolio Diversification: {diversification_score:.1f}/100")
```

### Portfolio Summary

```python
# Get comprehensive summary
summary = portfolio.get_portfolio_summary()

print(f"Total Capital: ${summary['total_capital']:,.2f}")
print(f"Active Strategies: {summary['active_strategies']}")
print(f"Current Regime: {summary['current_regime']}")
print(f"Portfolio Sharpe: {summary['portfolio_sharpe']:.2f}")
print(f"Diversification: {summary['diversification_score']:.1f}")

# Strategy-level performance
for name, perf in summary['strategy_performance'].items():
    print(f"\n{name}:")
    print(f"  Trades: {perf['total_trades']}")
    print(f"  Win Rate: {perf['win_rate_pct']:.1f}%")
    print(f"  P&L: ${perf['total_pnl']:,.2f}")
    print(f"  Allocation: {perf['allocation_pct']:.1f}%")
```

## Portfolio Optimization

### Optimization Algorithm

The portfolio manager uses a multi-factor optimization approach:

1. **Performance Scoring**
   - Win rate
   - Sharpe ratio
   - Maximum drawdown

2. **Regime Matching**
   - 1.5x bonus for preferred regimes
   - 0.8x penalty for non-preferred regimes

3. **Risk Adjustment**
   - Divide by risk multiplier
   - Higher risk = lower allocation

4. **Constraint Application**
   - Min/max allocation limits
   - Normalization to 100%

### Example Allocation

```python
# In BULL_TRENDING regime:
# - APEX_RSI: 45% (preferred regime)
# - TREND_FOLLOWING: 35% (preferred regime, higher risk)
# - MEAN_REVERSION: 20% (not preferred)

# In RANGING regime:
# - MEAN_REVERSION: 50% (preferred regime)
# - APEX_RSI: 40% (preferred regime)
# - TREND_FOLLOWING: 10% (not preferred)
```

## Integration Example

### Complete Multi-Strategy Trading Bot

```python
from bot.strategy_portfolio_manager import get_portfolio_manager, MarketRegime
from bot.performance_dashboard import get_performance_dashboard

# Initialize systems
portfolio = get_portfolio_manager(total_capital=100000.0)
dashboard = get_performance_dashboard(initial_capital=100000.0)

# Detect market regime
def detect_regime(market_data):
    # Your regime detection logic
    return MarketRegime.BULL_TRENDING

# Main trading loop
def trading_loop():
    while True:
        # Update regime
        regime = detect_regime(get_market_data())
        portfolio.update_market_regime(regime)
        
        # Get optimized allocation
        allocation = portfolio.optimize_allocation()
        
        # Execute trades for each strategy
        for strategy_name, alloc_pct in allocation.allocations.items():
            # Get allocated capital
            capital = portfolio.get_strategy_capital(strategy_name)
            
            # Execute strategy
            result = execute_strategy(strategy_name, capital)
            
            # Update performance
            if result:
                portfolio.update_strategy_performance(
                    strategy_name=strategy_name,
                    trade_result=result
                )
        
        # Update dashboard
        update_performance_snapshot()
        
        # Rebalance if needed
        current_capital = get_total_capital()
        portfolio.rebalance(current_capital)
        
        # Wait for next cycle
        sleep(300)  # 5 minutes
```

## Diversification Metrics

### Diversification Score

The diversification score (0-100) combines two factors:

1. **Correlation Score (50 points)**
   - Based on average correlation between strategies
   - Lower correlation = higher score
   - Formula: `(1 - avg_correlation) * 50`

2. **Concentration Score (50 points)**
   - Based on Herfindahl index
   - More balanced allocation = higher score
   - Perfect diversification (equal weights): 50 points

**Interpreting the Score:**
- **80-100**: Excellent diversification
- **60-80**: Good diversification
- **40-60**: Moderate diversification
- **20-40**: Poor diversification
- **0-20**: Highly concentrated

### Example Diversification

```python
# Good diversification
# - Low correlation between strategies
# - Balanced allocation
# Score: 85/100

# Poor diversification
# - High correlation (all trend-following)
# - Concentrated (80% in one strategy)
# Score: 25/100
```

## Strategy Selection Guidelines

### When to Use Each Strategy

#### APEX_RSI
- **Market Conditions**: Any
- **Best For**: Core allocation
- **Risk Level**: Medium
- **Correlation**: Low with trend strategies

#### TREND_FOLLOWING
- **Market Conditions**: Strong trends
- **Best For**: Capturing momentum
- **Risk Level**: High
- **Correlation**: High with other trend strategies

#### MEAN_REVERSION
- **Market Conditions**: Ranging markets
- **Best For**: Counter-trend trades
- **Risk Level**: Medium-Low
- **Correlation**: Negative with trend strategies

#### BREAKOUT
- **Market Conditions**: Consolidation to expansion
- **Best For**: Volatility increases
- **Risk Level**: High
- **Correlation**: Medium with trend strategies

#### VOLATILITY_EXPANSION
- **Market Conditions**: Increasing volatility
- **Best For**: Crisis/volatile periods
- **Risk Level**: Very High
- **Correlation**: Low with other strategies

#### PAIRS_TRADING
- **Market Conditions**: Any
- **Best For**: Market-neutral exposure
- **Risk Level**: Low-Medium
- **Correlation**: Very low with directional strategies

## Advanced Features

### Custom Regime Detection

```python
def detect_market_regime(price_data, volume_data):
    """Custom regime detection logic"""
    # Calculate metrics
    trend_strength = calculate_trend(price_data)
    volatility = calculate_volatility(price_data)
    
    # Classify regime
    if trend_strength > 0.7 and volatility < 0.3:
        return MarketRegime.BULL_TRENDING
    elif trend_strength < -0.7 and volatility < 0.3:
        return MarketRegime.BEAR_TRENDING
    elif abs(trend_strength) < 0.3:
        return MarketRegime.RANGING
    elif volatility > 0.5:
        return MarketRegime.CRISIS
    else:
        return MarketRegime.VOLATILE
```

### Dynamic Risk Multipliers

```python
def adjust_risk_multipliers(portfolio, market_conditions):
    """Dynamically adjust risk based on conditions"""
    
    for name, strategy in portfolio.strategies.items():
        if market_conditions['high_volatility']:
            # Reduce risk in high volatility
            strategy.risk_multiplier *= 0.8
        
        if market_conditions['trending']:
            # Increase trend strategy risk
            if strategy.strategy_type == TradingStrategy.TREND_FOLLOWING:
                strategy.risk_multiplier *= 1.2
```

### Rebalancing Triggers

```python
def check_rebalancing_needed(portfolio, current_allocation, target_allocation):
    """Check if rebalancing is needed"""
    
    max_deviation = 0.0
    
    for strategy in current_allocation:
        current = current_allocation[strategy]
        target = target_allocation[strategy]
        deviation = abs(current - target)
        max_deviation = max(max_deviation, deviation)
    
    # Rebalance if any strategy deviates by > 10%
    return max_deviation > 10.0
```

## Performance Attribution

Track which strategies contribute to overall performance:

```python
def calculate_strategy_attribution(portfolio):
    """Calculate performance attribution by strategy"""
    
    total_pnl = 0.0
    strategy_contributions = {}
    
    for name, perf in portfolio.performance.items():
        total_pnl += perf.total_pnl
    
    for name, perf in portfolio.performance.items():
        contribution_pct = (perf.total_pnl / total_pnl * 100) if total_pnl > 0 else 0
        strategy_contributions[name] = {
            'pnl': perf.total_pnl,
            'contribution_pct': contribution_pct,
            'allocation_pct': perf.current_allocation_pct
        }
    
    return strategy_contributions
```

## Best Practices

1. **Start with 2-3 Strategies**
   - Don't over-diversify initially
   - Focus on truly uncorrelated strategies

2. **Monitor Correlations**
   - Recalculate correlation matrix regularly
   - Remove highly correlated strategies

3. **Respect Min/Max Allocations**
   - Set reasonable bounds
   - Avoid over-concentration

4. **Regular Rebalancing**
   - Rebalance when deviations exceed 10%
   - Consider transaction costs

5. **Regime Detection**
   - Use robust regime detection
   - Don't switch too frequently

6. **Performance Review**
   - Review strategy performance monthly
   - Disable underperforming strategies

## Troubleshooting

### Concentrated Allocation
- Check min/max allocation constraints
- Review strategy performance scores
- Verify regime preferences

### High Correlation
- Add uncorrelated strategies
- Review strategy implementations
- Consider different timeframes

### Frequent Rebalancing
- Increase rebalancing threshold
- Use wider min/max bounds
- Reduce regime switch sensitivity

## Future Enhancements

- [ ] Machine learning for allocation optimization
- [ ] Multi-timeframe strategy coordination
- [ ] Options strategies integration
- [ ] Futures strategies
- [ ] Alternative data integration
- [ ] Risk parity allocation
- [ ] Black-Litterman optimization
- [ ] Transaction cost optimization

## Related Documentation

- [Capital Scaling Framework](CAPITAL_SCALING_FRAMEWORK.md)
- [Performance Dashboard](PERFORMANCE_DASHBOARD.md)
- [APEX Strategy](APEX_V71_DOCUMENTATION.md)
