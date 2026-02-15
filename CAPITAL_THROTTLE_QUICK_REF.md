# Automated Capital Throttle - Quick Reference

## Quick Start

```python
from bot.automated_capital_throttle import AutomatedCapitalThrottle

# Initialize
throttle = AutomatedCapitalThrottle(initial_capital=10000.0)

# Update capital
throttle.update_capital(current_balance)

# Record trades
throttle.record_trade(is_winner=True, profit_loss=150.0)

# Get max position size (respects throttling)
max_pos_pct = throttle.get_max_position_size()
```

## Capital Tiers

| Tier | Range | Max Pos% | Win Rate | PF | Max DD | Stress Test |
|------|-------|----------|----------|-----|--------|-------------|
| 1 | $0-10k | 2% | 50% | 1.2 | 15% | No |
| 2 | $10k-25k | 3% | 52% | 1.3 | 12% | No |
| 3 | $25k-50k | 4% | 53% | 1.4 | 10% | Yes |
| 4 | $50k+ | 5% | 55% | 1.5 | 8% | Yes |

## Throttle Triggers

1. **Low Win Rate** - Below tier requirement
2. **Low Profit Factor** - Below tier requirement  
3. **Excessive Drawdown** - Above tier maximum
4. **High Ruin Risk** - >5% probability
5. **Stress Test Required** - At $50k threshold
6. **Stress Test Failed** - Can't pass 25% DD test

## Stress Test at $50k

Before scaling past $50k:
- Simulates 25% drawdown
- Tests 30-day recovery (90 trades)
- Requires 50% recovery probability
- Must pass to continue scaling

## Integration Pattern

```python
# In your trading strategy
class YourStrategy:
    def __init__(self, balance):
        self.throttle = AutomatedCapitalThrottle(balance)
        self.risk_mgr = AdaptiveRiskManager()
    
    def execute_trade(self, signal):
        # Check throttle
        if self.throttle.state.is_throttled:
            logger.warning(f"Throttled: {self.throttle.state.throttle_reason}")
            return None
        
        # Get position size (use minimum of both limits)
        throttle_limit = self.throttle.get_max_position_size()
        risk_limit = self.risk_mgr.calculate_position_size(...)
        position_pct = min(throttle_limit, risk_limit)
        
        # Execute
        order = self.place_order(signal, position_pct)
        
        # Record outcome
        if order.filled:
            self.throttle.record_trade(
                is_winner=order.profit > 0,
                profit_loss=order.profit
            )
            self.throttle.update_capital(self.get_balance())
        
        return order
```

## Status Monitoring

```python
# Get comprehensive status
status = throttle.get_status_report()

print(f"Capital: ${status['capital']['current']:,.2f}")
print(f"Win Rate: {status['performance']['win_rate']:.2%}")
print(f"Ruin Risk: {status['risk']['ruin_probability']:.4%}")
print(f"Throttled: {status['throttle']['is_throttled']}")
```

## Configuration

```python
from bot.automated_capital_throttle import ThrottleConfig

config = ThrottleConfig(
    enable_parallel_risk_modeling=True,
    risk_update_interval_trades=10,  # Run risk analysis every N trades
    max_acceptable_ruin_probability=0.05,  # 5% max
    enable_auto_throttle=True
)

throttle = AutomatedCapitalThrottle(initial_capital, config=config)
```

## Files

- **Implementation**: `bot/automated_capital_throttle.py`
- **Risk Engine**: `bot/risk_of_ruin_engine.py`
- **Tests**: `test_automated_capital_throttle.py`
- **Docs**: `AUTOMATED_CAPITAL_THROTTLE.md`
- **Example**: `example_capital_throttle_integration.py`
- **State File**: `data/capital_throttle_state.json`

## Key Methods

```python
# Update capital after trades
throttle.update_capital(new_balance)

# Record trade outcome
throttle.record_trade(is_winner=bool, profit_loss=float)

# Get max position size (throttled)
max_pos = throttle.get_max_position_size()

# Run stress test
results = throttle.simulate_drawdown_stress_test(
    drawdown_pct=25.0,
    duration_days=30
)

# Get status
status = throttle.get_status_report()
```

## Troubleshooting

**Throttle won't release?**
- Check win rate ≥ required
- Check profit factor ≥ required
- Check drawdown ≤ maximum
- Run stress test if at $50k+

**Stress test failing?**
- Need win rate ≥ 55%
- Need profit factor ≥ 1.5
- Need 50+ trade history
- May need to reduce position sizes

**High ruin probability?**
- Reduce position sizes
- Improve win rate
- Improve profit factor
- Review strategy edge

## Performance Impact

- **Memory**: ~5MB
- **CPU**: Minimal (async risk analysis)
- **Latency**: <10ms per check
- **Disk**: State saved after each trade

## See Also

- Full documentation: `AUTOMATED_CAPITAL_THROTTLE.md`
- Integration example: `example_capital_throttle_integration.py`
- Risk management: `RISK_MANAGEMENT_GUIDE.md`
- Capital scaling: `CAPITAL_SCALING_FRAMEWORK.md`
