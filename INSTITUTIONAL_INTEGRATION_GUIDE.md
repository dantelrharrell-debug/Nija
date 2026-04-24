# Institutional Capital Management System - Integration Guide

## Overview

The Institutional Capital Management System transforms NIJA from a trading bot into a true capital management system with institutional-grade risk controls. This guide shows how to integrate these features into your trading workflow.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│        Capital Preservation Override                 │  ← Emergency Brake
│        (Highest Priority - Overrides Everything)     │
└────────────────────┬─────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────┐
│        Institutional Capital Manager                 │  ← Master Coordinator
│        (Coordinates All Features)                    │
└────────────────────┬─────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────┐
│  Feature Layer:                                      │
│  • Performance Scaling   • Correlation Compression   │
│  • Drawdown Throttle     • Liquidity Gate            │
│  • Volatility Adjustment                             │
└────────────────────┬─────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────┐
│        Risk Manager (Existing)                       │  ← Position Sizing
└────────────────────┬─────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────────┐
│        Execution Engine                              │  ← Trade Execution
└──────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Basic Integration

```python
from bot.institutional_capital_manager import create_institutional_manager
from bot.risk_manager import AdaptiveRiskManager

# Initialize institutional manager
institutional_mgr = create_institutional_manager(
    base_capital=10_000.0,
    tier="INCOME"
)

# Initialize risk manager (existing)
risk_mgr = AdaptiveRiskManager()

# Calculate position size
def calculate_position_size(symbol, market_data, portfolio_state=None):
    # 1. Get base position size from risk manager
    base_size = risk_mgr.calculate_position_size(
        symbol=symbol,
        capital=institutional_mgr.metrics.current_capital,
        # ... other risk manager parameters
    )
    
    # 2. Apply institutional adjustments
    adjusted_size, reasoning = institutional_mgr.calculate_position_size(
        base_size=base_size,
        symbol=symbol,
        market_data=market_data,
        portfolio_state=portfolio_state
    )
    
    # 3. Check if trading is allowed
    can_trade, reason = institutional_mgr.can_trade()
    if not can_trade:
        return 0.0, f"Trading blocked: {reason}"
    
    return adjusted_size, reasoning
```

### 2. Update Metrics Regularly

```python
# Update metrics after each trade
def on_trade_complete(profit_loss, new_capital, portfolio_correlation):
    institutional_mgr.update_metrics(
        current_capital=new_capital,
        portfolio_correlation=portfolio_correlation,
        monthly_return=calculate_monthly_return(),
        active_positions=len(get_active_positions())
    )
```

### 3. Monitor Risk Status

```python
# Get comprehensive risk report
def print_risk_status():
    report = institutional_mgr.get_risk_report()
    print(report)
    
    # Check specific conditions
    if institutional_mgr.metrics.current_throttle_level != RiskThrottleLevel.NORMAL:
        print(f"⚠️  Risk throttle active: {institutional_mgr.metrics.current_throttle_level.value}")
    
    if institutional_mgr.metrics.composite_multiplier < 0.5:
        print(f"⚠️  Position sizes reduced to {institutional_mgr.metrics.composite_multiplier:.1%}")
```

## Feature Configuration

### Custom Configuration

```python
from bot.institutional_capital_manager import InstitutionalConfig

config = InstitutionalConfig(
    # Correlation compression
    enable_correlation_compression=True,
    correlation_threshold=0.65,
    max_correlation_penalty=0.5,
    
    # Liquidity gating
    enable_liquidity_gating=True,
    tier_volume_multipliers={
        "INCOME": 3.0,
        "LIVABLE": 4.0,
        "BALLER": 5.0
    },
    
    # Drawdown throttle
    enable_drawdown_throttle=True,
    throttle_thresholds={
        "REDUCED": 5.0,
        "CONSERVATIVE": 10.0,
        "MINIMAL": 15.0,
        "PRESERVATION": 20.0
    },
    
    # Performance scaling
    enable_performance_scaling=True,
    scale_up_threshold=0.15,
    scale_down_threshold=-0.05,
    
    # Volatility adjustment
    enable_volatility_adjustment=True,
    
    # Capital preservation
    enable_capital_preservation=True,
    preservation_floor_pct=0.90,
    preservation_override_drawdown=25.0
)

mgr = InstitutionalCapitalManager(10_000.0, "INCOME", config)
```

## Individual Feature Usage

### Performance-Based Risk Scaling

```python
from bot.performance_based_risk_scaling import create_performance_scaling, PerformanceMetrics

# Initialize
scaling = create_performance_scaling()

# Update with current performance
metrics = PerformanceMetrics(
    monthly_return=0.12,
    sharpe_ratio=2.0,
    win_rate=0.65,
    profit_factor=2.5,
    current_streak=3,
    current_drawdown_pct=2.0,
    confidence_score=0.75
)
scaling.update_metrics(metrics)

# Calculate scaled position
result = scaling.calculate_scale_factor(base_position_size=1000.0)
print(f"Scaled size: ${result.scaled_size:.2f}")
print(f"Scale factor: {result.scale_factor:.2%}")
print(f"Performance level: {result.performance_level.value}")
```

### Liquidity & Volume Gating

```python
from bot.liquidity_volume_gate import create_liquidity_gate

# Initialize for tier
gate = create_liquidity_gate("INCOME")

# Check market liquidity
market_data = {
    'volume_24h': 15_000_000,
    'avg_volume': 14_000_000,
    'bid': 50_000,
    'ask': 50_015,
    'price': 50_007.5,
    'market_depth_bid': 200_000,
    'market_depth_ask': 180_000
}

result = gate.check_liquidity("BTC-USD", market_data, position_size_usd=5000)

if result.passed:
    print(f"✅ Liquidity check passed - Score: {result.liquidity_score:.2f}")
else:
    print(f"❌ Liquidity check failed")
    print(f"Violations: {', '.join(result.violations)}")
```

### Capital Preservation Override

```python
from bot.capital_preservation_override import create_preservation_override

# Initialize
preservation = create_preservation_override(
    base_capital=10_000.0
)

# Update capital after trades
preservation.update_capital(9_500.0)

# Check if trading allowed
can_trade, reason = preservation.can_trade()
if not can_trade:
    print(f"🚨 Trading halted: {reason}")
    
    # Get status
    print(preservation.get_status_report())
    
    # Manual reset (after review)
    # preservation.manual_reset(reset_by="trader_001", notes="Issue resolved")
```

## Integration with Existing Systems

### With Risk Manager

```python
class EnhancedRiskManager:
    def __init__(self, base_capital, tier):
        self.base_risk_mgr = AdaptiveRiskManager()
        self.institutional_mgr = create_institutional_manager(base_capital, tier)
    
    def calculate_position(self, symbol, market_data, portfolio_state=None):
        # Step 1: Base risk calculation
        base_size = self.base_risk_mgr.calculate_position_size(
            symbol=symbol,
            capital=self.institutional_mgr.metrics.current_capital,
            # ... other parameters
        )
        
        # Step 2: Institutional adjustments
        adjusted_size, reasoning = self.institutional_mgr.calculate_position_size(
            base_size=base_size,
            symbol=symbol,
            market_data=market_data,
            portfolio_state=portfolio_state
        )
        
        return {
            'size': adjusted_size,
            'base_size': base_size,
            'adjustment_factor': adjusted_size / base_size if base_size > 0 else 0,
            'reasoning': reasoning
        }
```

### With Trading Strategy

```python
from bot.nija_apex_strategy import NijaApexStrategyV71

class InstitutionalStrategy(NijaApexStrategyV71):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add institutional layer
        self.institutional_mgr = create_institutional_manager(
            base_capital=self.capital,
            tier=self.tier
        )
    
    def enter_position(self, symbol, signal_strength):
        # Get base position size from strategy
        base_size = self.calculate_base_position_size(symbol, signal_strength)
        
        # Get market data
        market_data = self.get_market_data(symbol)
        portfolio_state = self.get_portfolio_state()
        
        # Apply institutional adjustments
        adjusted_size, reasoning = self.institutional_mgr.calculate_position_size(
            base_size=base_size,
            symbol=symbol,
            market_data=market_data,
            portfolio_state=portfolio_state
        )
        
        # Check if trading allowed
        can_trade, reason = self.institutional_mgr.can_trade()
        if not can_trade:
            self.log(f"Entry blocked: {reason}")
            return None
        
        if adjusted_size < self.min_position_size:
            self.log(f"Position size {adjusted_size} below minimum after adjustments")
            return None
        
        # Execute trade
        self.log(f"Position adjusted: ${base_size:.2f} → ${adjusted_size:.2f}")
        self.log(f"Reasoning: {reasoning}")
        
        return self.execute_trade(symbol, adjusted_size)
    
    def update_after_trade(self, trade_result):
        # Update institutional metrics
        self.institutional_mgr.update_metrics(
            current_capital=self.get_current_capital(),
            portfolio_correlation=self.calculate_portfolio_correlation(),
            monthly_return=self.get_monthly_return(),
            active_positions=len(self.positions)
        )
        
        # Generate report if throttled
        if self.institutional_mgr.metrics.current_throttle_level != RiskThrottleLevel.NORMAL:
            self.log(self.institutional_mgr.get_risk_report())
```

## Best Practices

### 1. Regular Metric Updates

Update metrics after every trade and at least once per hour:

```python
def update_all_metrics():
    institutional_mgr.update_metrics(
        current_capital=get_current_capital(),
        portfolio_correlation=calculate_correlation(),
        monthly_return=get_monthly_return(),
        active_positions=count_positions(),
        sharpe_ratio=calculate_sharpe(),
        win_rate=calculate_win_rate()
    )
```

### 2. Monitor Throttle Levels

Set up alerts when throttle level changes:

```python
def check_throttle_level():
    level = institutional_mgr.metrics.current_throttle_level
    
    if level == RiskThrottleLevel.REDUCED:
        send_alert("⚠️  Risk throttle: REDUCED - Positions reduced to 75%")
    elif level == RiskThrottleLevel.CONSERVATIVE:
        send_alert("⚠️  Risk throttle: CONSERVATIVE - Positions reduced to 50%")
    elif level == RiskThrottleLevel.MINIMAL:
        send_alert("🚨 Risk throttle: MINIMAL - Positions reduced to 25%")
    elif level == RiskThrottleLevel.PRESERVATION:
        send_alert("🚨 Risk throttle: PRESERVATION - Trading halted!")
```

### 3. Daily Risk Reports

Generate and review daily reports:

```python
def daily_risk_report():
    report = institutional_mgr.get_risk_report()
    
    # Save to file
    with open(f"reports/risk_report_{datetime.now().date()}.txt", "w") as f:
        f.write(report)
    
    # Send to monitoring system
    send_to_dashboard(report)
    
    # Alert if concerning
    if institutional_mgr.metrics.drawdown_pct > 10:
        send_alert(f"⚠️  Drawdown: {institutional_mgr.metrics.drawdown_pct:.2f}%")
```

### 4. Test with Paper Trading

Always test institutional features in paper trading first:

```python
# Use test capital for paper trading
if PAPER_TRADING_MODE:
    institutional_mgr = create_institutional_manager(
        base_capital=10_000.0,  # Paper trading capital
        tier="INCOME"
    )
else:
    institutional_mgr = create_institutional_manager(
        base_capital=get_live_capital(),
        tier=get_current_tier()
    )
```

## Monitoring & Alerts

### Key Metrics to Monitor

1. **Composite Multiplier**: Overall position size adjustment
   - < 0.5: Severely reduced positions
   - 0.5-0.75: Moderately reduced
   - 0.75-1.0: Slightly reduced
   - 1.0+: Normal or increased

2. **Throttle Level**: Current risk state
   - NORMAL: Full trading
   - REDUCED: 75% positions
   - CONSERVATIVE: 50% positions
   - MINIMAL: 25% positions
   - PRESERVATION: Trading halted

3. **Drawdown Percentage**: Capital loss from peak
   - < 5%: Normal
   - 5-10%: Monitor closely
   - 10-15%: Take action
   - 15-20%: Critical
   - > 20%: Emergency

4. **Liquidity Factor**: Market liquidity status
   - 1.0: Passed
   - 0.0: Failed (trade rejected)

### Alert Configuration

```python
def setup_alerts():
    alerts = {
        'drawdown_5pct': lambda: institutional_mgr.metrics.drawdown_pct >= 5,
        'drawdown_10pct': lambda: institutional_mgr.metrics.drawdown_pct >= 10,
        'throttle_reduced': lambda: institutional_mgr.metrics.current_throttle_level != RiskThrottleLevel.NORMAL,
        'composite_low': lambda: institutional_mgr.metrics.composite_multiplier < 0.5,
        'preservation_triggered': lambda: not institutional_mgr.can_trade()[0]
    }
    
    return alerts
```

## Troubleshooting

### Issue: All trades rejected

**Check:**
1. Capital preservation status: `preservation.get_status_report()`
2. Throttle level: `institutional_mgr.metrics.current_throttle_level`
3. Liquidity requirements: Ensure market meets tier requirements

**Solution:**
```python
# Check each component
can_trade, reason = institutional_mgr.can_trade()
print(f"Can trade: {can_trade}, Reason: {reason}")

# Check liquidity
liquidity_result = gate.check_liquidity(symbol, market_data)
print(f"Liquidity passed: {liquidity_result.passed}")
```

### Issue: Position sizes too small

**Check:**
1. Performance scaling factor
2. Correlation compression
3. Volatility adjustment
4. Drawdown throttle

**Solution:**
```python
# Debug position size calculation
base_size = 1000.0
adjusted_size, reasoning = institutional_mgr.calculate_position_size(
    base_size, symbol, market_data, portfolio_state
)
print(f"Base: ${base_size}, Adjusted: ${adjusted_size}")
print(f"Reasoning: {reasoning}")
print(f"Composite multiplier: {institutional_mgr.metrics.composite_multiplier:.2%}")
```

### Issue: Preservation mode stuck

**Check:**
1. Manual reset requirement
2. Minimum review period

**Solution:**
```python
# Reset preservation mode (after proper review)
preservation.manual_reset(
    reset_by="admin",
    notes="Capital replenished, ready to resume trading"
)
```

## Performance Optimization

### Caching Market Data

```python
class MarketDataCache:
    def __init__(self, ttl_seconds=60):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get_market_data(self, symbol):
        if symbol in self.cache:
            data, timestamp = self.cache[symbol]
            if time.time() - timestamp < self.ttl:
                return data
        
        # Fetch fresh data
        data = self.fetch_market_data(symbol)
        self.cache[symbol] = (data, time.time())
        return data
```

### Batch Position Calculations

```python
def calculate_positions_batch(symbols, market_data_dict):
    results = {}
    
    # Get portfolio state once
    portfolio_state = get_portfolio_state()
    
    for symbol in symbols:
        market_data = market_data_dict[symbol]
        
        base_size = calculate_base_size(symbol)
        adjusted_size, reasoning = institutional_mgr.calculate_position_size(
            base_size, symbol, market_data, portfolio_state
        )
        
        results[symbol] = {
            'size': adjusted_size,
            'reasoning': reasoning
        }
    
    return results
```

## Conclusion

The Institutional Capital Management System provides multiple layers of risk protection and optimization. By following this integration guide, you can transform NIJA into a true institutional-grade capital management system that protects capital while maximizing returns.

For questions or issues, refer to the test suite in `test_institutional_features.py` for working examples.
