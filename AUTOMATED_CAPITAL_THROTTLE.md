# Automated Capital Throttle Documentation

## Overview

The Automated Capital Throttle is a sophisticated risk management system that ensures NIJA scales capital safely and maintains discipline at institutional standards.

## Key Features

### 1. Progressive Capital Thresholds

Capital is divided into 4 tiers with increasingly strict requirements:

| Tier | Capital Range | Max Position Size | Required Win Rate | Required Profit Factor | Max Drawdown |
|------|---------------|-------------------|-------------------|------------------------|--------------|
| 1    | $0 - $10k     | 2%                | 50%               | 1.2                    | 15%          |
| 2    | $10k - $25k   | 3%                | 52%               | 1.3                    | 12%          |
| 3    | $25k - $50k   | 4%                | 53%               | 1.4                    | 10%          |
| 4    | $50k+         | 5%                | 55%               | 1.5                    | 8%           |

### 2. Parallel Risk-of-Ruin Modeling

The system continuously monitors risk-of-ruin probability using Monte Carlo simulation:

- **Update Frequency**: Every 10 trades (configurable)
- **Simulations**: 5,000 Monte Carlo paths
- **Max Acceptable Risk**: 5% ruin probability
- **Auto-Throttle**: Activated if ruin risk exceeds threshold

### 3. 25% Drawdown Stress Test

Before scaling past $50k, the strategy must pass a severe drawdown stress test:

- **Test**: Simulate 25% account drawdown
- **Recovery Target**: Must demonstrate 50% recovery probability within 30 days
- **Trading Volume**: Assumes 3 trades per day
- **Simulations**: 1,000 recovery scenarios

### 4. Automatic Position Throttling

Position sizes are automatically reduced based on throttle level:

| Throttle Level | Position Size Multiplier | Description |
|----------------|-------------------------|-------------|
| UNRESTRICTED   | 100%                    | Normal operations |
| CONSERVATIVE   | 75%                     | Light throttling |
| MODERATE       | 50%                     | Moderate throttling |
| STRICT         | 25%                     | Heavy throttling |
| LOCKED         | 0%                      | No trading |

## Usage

### Basic Integration

```python
from bot.automated_capital_throttle import AutomatedCapitalThrottle

# Initialize throttle
throttle = AutomatedCapitalThrottle(initial_capital=10000.0)

# Update capital after trades
throttle.update_capital(current_capital=11500.0)

# Record trade outcomes
throttle.record_trade(is_winner=True, profit_loss=150.0)

# Get maximum position size
max_position_pct = throttle.get_max_position_size()

# Check status
status = throttle.get_status_report()
print(f"Throttled: {status['throttle']['is_throttled']}")
print(f"Win Rate: {status['performance']['win_rate']:.2%}")
print(f"Ruin Probability: {status['risk']['ruin_probability']:.4%}")
```

### Running Stress Test

```python
# Before scaling past $50k, run stress test
results = throttle.simulate_drawdown_stress_test(
    drawdown_pct=25.0,
    duration_days=30
)

if results['passed']:
    print("✅ Approved for scaling past $50k")
else:
    print(f"❌ Failed stress test: {results['recovery_probability']:.2%} recovery probability")
```

### Custom Configuration

```python
from bot.automated_capital_throttle import (
    AutomatedCapitalThrottle,
    ThrottleConfig,
    CapitalThreshold
)

# Create custom config
config = ThrottleConfig(
    enable_parallel_risk_modeling=True,
    risk_update_interval_trades=20,  # Run risk analysis every 20 trades
    max_acceptable_ruin_probability=0.03,  # 3% max ruin risk
    enable_auto_throttle=True
)

throttle = AutomatedCapitalThrottle(
    initial_capital=25000.0,
    config=config
)
```

## Throttle Triggers

The system will automatically throttle capital when:

1. **Win Rate Below Requirement**: Current win rate < threshold requirement
2. **Profit Factor Below Requirement**: Current PF < threshold requirement
3. **Excessive Drawdown**: Current drawdown > threshold maximum
4. **High Ruin Risk**: Risk-of-ruin probability > 5%
5. **Stress Test Required**: Crossing $50k threshold without passing stress test
6. **Stress Test Failed**: Failed to pass 25% drawdown recovery test

## State Persistence

The throttle state is automatically saved to:
```
/data/capital_throttle_state.json
```

This includes:
- Performance metrics (trades, win rate, profit factor)
- Current capital and peak capital
- Throttle status and reason
- Stress test results
- Risk-of-ruin analysis results

## Integration with Existing Risk Management

### With risk_manager.py

```python
from bot.risk_manager import AdaptiveRiskManager
from bot.automated_capital_throttle import AutomatedCapitalThrottle

# Initialize both systems
risk_mgr = AdaptiveRiskManager()
throttle = AutomatedCapitalThrottle(initial_capital=balance)

# Use throttle to limit position sizes
max_pos_from_throttle = throttle.get_max_position_size()
max_pos_from_risk_mgr = risk_mgr.calculate_position_size(...)

# Use the more conservative limit
final_pos_size = min(max_pos_from_throttle, max_pos_from_risk_mgr)
```

### With capital_scaling_engine.py

```python
from bot.capital_scaling_engine import CapitalScalingEngine
from bot.automated_capital_throttle import AutomatedCapitalThrottle

scaling_engine = CapitalScalingEngine(base_capital=balance)
throttle = AutomatedCapitalThrottle(initial_capital=balance)

# Check throttle before allowing capital scaling
if not throttle.state.is_throttled:
    # Allow capital scaling
    new_capital = scaling_engine.get_scaled_capital()
else:
    # Throttle active, use reduced capital
    print(f"Throttle active: {throttle.state.throttle_reason}")
```

## Monitoring and Alerts

### Status Report

```python
status = throttle.get_status_report()

print(f"""
Capital Status:
  Current: ${status['capital']['current']:,.2f}
  Peak: ${status['capital']['peak']:,.2f}
  Drawdown: {status['capital']['drawdown_pct']:.2f}%

Performance:
  Win Rate: {status['performance']['win_rate']:.2%}
  Profit Factor: {status['performance']['profit_factor']:.2f}
  Total Trades: {status['performance']['total_trades']}

Throttle Status:
  Active: {status['throttle']['is_throttled']}
  Reason: {status['throttle']['reason']}
  Level: {status['throttle']['level']}
  Max Position: {status['throttle']['max_position_size']*100:.2f}%

Risk Analysis:
  Ruin Probability: {status['risk']['ruin_probability']:.4%}
  Max Acceptable: {status['risk']['max_acceptable']:.4%}

Stress Test:
  Passed: {status['stress_test']['passed']}
  Last Run: {status['stress_test']['last_run']}
""")
```

## Best Practices

1. **Initialize Early**: Create throttle instance at bot startup
2. **Update Regularly**: Call `update_capital()` after each trade
3. **Record All Trades**: Use `record_trade()` for accurate metrics
4. **Monitor Status**: Check throttle status before placing new orders
5. **Respect Throttling**: Never override position size limits
6. **Run Stress Tests**: Complete stress test before major capital increases
7. **Review Metrics**: Regularly check risk-of-ruin probability
8. **Persist State**: Ensure state file is backed up

## Example Integration in Trading Strategy

```python
class NIJATradingStrategy:
    def __init__(self, balance):
        self.throttle = AutomatedCapitalThrottle(initial_capital=balance)
        self.risk_mgr = AdaptiveRiskManager()
    
    def execute_trade(self, signal, current_balance):
        # Update throttle with current balance
        self.throttle.update_capital(current_balance)
        
        # Check if throttled
        if self.throttle.state.is_throttled:
            logger.warning(f"Trading throttled: {self.throttle.state.throttle_reason}")
            return None
        
        # Get throttled position size
        max_pos_pct = self.throttle.get_max_position_size()
        
        # Calculate position size with both risk manager and throttle
        risk_mgr_size = self.risk_mgr.calculate_position_size(...)
        final_size = min(risk_mgr_size, current_balance * max_pos_pct)
        
        # Place trade
        order = self.place_order(signal, final_size)
        
        # Record outcome
        if order.filled:
            is_winner = order.profit > 0
            self.throttle.record_trade(is_winner, order.profit)
        
        return order
    
    def check_scaling_readiness(self):
        """Check if ready to scale past $50k"""
        if self.throttle.state.current_capital >= 50000:
            if not self.throttle.state.stress_test_passed:
                logger.info("Running $50k stress test...")
                results = self.throttle.simulate_drawdown_stress_test(
                    drawdown_pct=25.0,
                    duration_days=30
                )
                return results['passed']
        return True
```

## Technical Details

### Risk-of-Ruin Calculation

Uses multiple methods:
1. **Theoretical**: Gambler's ruin formula
2. **Kelly Criterion**: Optimal position sizing
3. **Monte Carlo**: 5,000 simulated trading sequences
4. **Regime Analysis**: Bull, bear, and high volatility scenarios

### Drawdown Simulation Algorithm

```
1. Start capital at 25% drawdown point
2. Define recovery target (50% of drawdown recovered)
3. Run 1,000 simulations:
   - Each simulation trades for 30 days (90 trades)
   - Use current win rate and profit factor
   - Check if recovery target reached
4. Calculate recovery probability
5. Pass if probability >= 50%
```

### State Persistence Format

```json
{
  "current_capital": 52000.0,
  "peak_capital": 55000.0,
  "current_drawdown_pct": 5.45,
  "total_trades": 287,
  "winning_trades": 165,
  "losing_trades": 122,
  "current_win_rate": 0.5749,
  "current_profit_factor": 1.62,
  "current_ruin_probability": 0.0023,
  "is_throttled": false,
  "throttle_reason": "",
  "stress_test_passed": true,
  "stress_test_last_run": "2026-02-15T10:30:00",
  "stress_test_results": {
    "passed": true,
    "recovery_probability": 0.73,
    "drawdown_pct": 25.0
  }
}
```

## Troubleshooting

### Throttle Won't Release

**Problem**: Throttle remains active despite good performance

**Solutions**:
1. Check all requirements are met (win rate, profit factor, drawdown)
2. Verify sufficient trade history (minimum 20 trades)
3. Run stress test if at $50k+ threshold
4. Check if ruin probability is below 5%

### Stress Test Keeps Failing

**Problem**: Cannot pass 25% drawdown stress test

**Solutions**:
1. Increase win rate above 55%
2. Improve profit factor above 1.5
3. Build more trade history (50+ trades)
4. Reduce position sizes to lower risk
5. Wait for better market conditions

### High Ruin Probability

**Problem**: Risk-of-ruin probability exceeds 5%

**Solutions**:
1. Reduce position sizes
2. Improve win rate or profit factor
3. Review strategy for edge
4. Check for over-leverage
5. Review recent losing streak

## Performance Impact

- **Memory**: ~5MB for state storage
- **CPU**: Minimal (risk analysis runs asynchronously every 10 trades)
- **Latency**: <10ms for throttle checks
- **Disk I/O**: Minimal (state saved after each trade)

## Version History

- **v1.0** (Feb 15, 2026): Initial release
  - Progressive capital thresholds
  - Parallel risk-of-ruin modeling
  - 25% drawdown stress test
  - Automatic position throttling
  - State persistence

## Support

For issues or questions, refer to:
- Risk management documentation: `RISK_MANAGEMENT_GUIDE.md`
- Capital scaling guide: `CAPITAL_SCALING_FRAMEWORK.md`
- Risk-of-ruin engine: `bot/risk_of_ruin_engine.py`
