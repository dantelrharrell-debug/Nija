# NIJA Auto-Optimization Engine - Quick Start Guide

## 🚀 Get Up and Running in 5 Minutes

The Auto-Optimization Engine is NIJA's self-improving AI control loop. This guide will get you started quickly.

---

## Step 1: Basic Setup (2 minutes)

### Option A: Standalone Usage

```python
from bot.auto_optimization_engine import get_auto_optimizer

# Initialize with default settings
optimizer = get_auto_optimizer()

# That's it! The engine is now running.
```

### Option B: Integrated with NIJA Brain (Recommended)

```python
from core.nija_brain import create_nija_brain

# NIJA Brain automatically includes auto-optimizer
brain = create_nija_brain(
    total_capital=10000.0,
    config={
        'auto_optimization': {
            'optimization_interval_hours': 168,  # Weekly
            'min_trades_before_optimization': 100
        }
    }
)

# Auto-optimizer is now active at brain.auto_optimizer
```

---

## Step 2: Record Trades (1 minute)

Every time a trade completes, record it:

### Simple Version

```python
# Record each trade result
optimizer.record_trade_result(
    strategy_name="apex_v72",
    trade_result={
        'pnl': 150.00,          # Profit/loss in dollars
        'return_pct': 0.03,     # 3% return
        'fees': 3.00,           # Trading fees
        'duration_minutes': 45  # How long trade was open
    }
)
```

### Complete Version (Better)

```python
optimizer.record_trade_result(
    strategy_name="apex_v72",
    trade_result={
        # Required fields
        'pnl': 150.00,
        'return_pct': 0.03,
        'fees': 3.00,
        
        # Optional but recommended
        'duration_minutes': 45,
        'max_favorable_excursion': 0.05,  # Best price during trade
        'max_adverse_excursion': -0.01,   # Worst price during trade
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 50000.00,
        'exit_price': 51500.00
    }
)
```

### With NIJA Brain (Automatic)

```python
# Just record the trade with brain - optimizer gets it automatically
brain.record_trade_completion({
    'trade_id': 'trade_123',
    'strategy_id': 'apex_v72',
    'symbol': 'BTC-USD',
    'pnl': 150.00,
    'return_pct': 0.03,
    # ... other fields
})

# Optimizer automatically receives and processes the trade
```

---

## Step 3: Monitor Status (30 seconds)

Check what's happening:

```python
# Get current status
status = optimizer.get_status()

print(f"State: {status['state']}")
print(f"Performance Score: {status['current_performance_score']:.2f}/100")
print(f"Trades Tracked: {status['total_trades_tracked']}")
print(f"Cycles Completed: {status['optimization_cycles_completed']}")
```

**Output:**
```
State: monitoring
Performance Score: 78.5/100
Trades Tracked: 247
Cycles Completed: 3
```

---

## Step 4: Let It Run (1 minute)

The engine now runs automatically!

### What Happens Automatically

1. **Monitoring** (Continuous)
   - Tracks every trade
   - Calculates performance metrics
   - Watches for degradation

2. **Optimization** (Scheduled)
   - Runs weekly (configurable)
   - Uses AI to find better parameters
   - Tests on out-of-sample data

3. **Deployment** (When Ready)
   - Deploys if improvement > 5%
   - Validates against overfitting
   - Updates your strategy automatically

4. **Rollback** (If Needed)
   - Monitors new parameters
   - Reverts if performance drops
   - Keeps you safe

---

## Complete Example: End-to-End

Here's a complete example showing typical usage:

```python
from bot.auto_optimization_engine import get_auto_optimizer
from datetime import datetime

# 1. Initialize
optimizer = get_auto_optimizer(
    state_dir="./data/optimization",
    config={
        'optimization_interval_hours': 168,  # Weekly
        'min_trades_before_optimization': 100,
        'min_improvement_for_deployment': 5.0,  # 5% minimum
        'degradation_threshold_pct': -10.0  # Trigger if -10% drop
    }
)

print("✅ Auto-Optimizer initialized")

# 2. Simulate trading (your actual trading loop)
for i in range(200):
    # Your trading logic here...
    # When trade completes:
    
    trade_result = {
        'pnl': 100.00 if i % 2 == 0 else -50.00,  # Win/loss
        'return_pct': 0.02 if i % 2 == 0 else -0.01,
        'fees': 2.00,
        'duration_minutes': 30
    }
    
    # Record with optimizer
    optimizer.record_trade_result("apex_v72", trade_result)
    
    # Every 50 trades, check status
    if (i + 1) % 50 == 0:
        status = optimizer.get_status()
        print(f"\n--- After {i + 1} trades ---")
        print(f"Performance Score: {status['current_performance_score']:.2f}")
        print(f"State: {status['state']}")
        print(f"Win Rate: {optimizer.current_metrics.win_rate:.1%}")
        print(f"Sharpe: {optimizer.current_metrics.sharpe_ratio:.2f}")

# 3. Check final status
final_status = optimizer.get_status()
print("\n=== Final Status ===")
print(f"Total Trades: {final_status['total_trades_tracked']}")
print(f"Performance Score: {final_status['current_performance_score']:.2f}")
print(f"Optimization Cycles: {final_status['optimization_cycles_completed']}")

# 4. View optimization history
if optimizer.optimization_cycles:
    print("\n=== Optimization History ===")
    for cycle in optimizer.optimization_cycles[-3:]:  # Last 3 cycles
        print(f"\nCycle: {cycle.cycle_id}")
        print(f"  Trigger: {cycle.trigger_reason}")
        print(f"  Improvement: {cycle.improvement_pct:+.1f}%")
        print(f"  Deployed: {'✅' if cycle.was_deployed else '❌'}")
```

---

## Configuration Presets

### Conservative (Recommended for Beginners)

```python
config = {
    'optimization_interval_hours': 336,  # Every 2 weeks
    'min_trades_before_optimization': 200,  # Need lots of data
    'min_improvement_for_deployment': 10.0,  # Only deploy big wins
    'degradation_threshold_pct': -15.0,  # Tolerant to variance
}
```

**Best for:**
- New users
- Small account sizes
- Testing the system
- Risk-averse traders

### Balanced (Recommended for Most Users)

```python
config = {
    'optimization_interval_hours': 168,  # Weekly
    'min_trades_before_optimization': 100,
    'min_improvement_for_deployment': 5.0,
    'degradation_threshold_pct': -10.0,
}
```

**Best for:**
- Active trading bots
- Medium to large accounts
- Experienced users
- Standard use case

### Aggressive (Advanced Users)

```python
config = {
    'optimization_interval_hours': 84,  # Twice per week
    'min_trades_before_optimization': 50,
    'min_improvement_for_deployment': 3.0,
    'degradation_threshold_pct': -8.0,
}
```

**Best for:**
- High-frequency trading
- Large accounts
- Experienced traders
- Maximum optimization

---

## Common Use Cases

### Use Case 1: Live Trading Bot

```python
from bot.auto_optimization_engine import get_auto_optimizer

class TradingBot:
    def __init__(self):
        self.optimizer = get_auto_optimizer()
        
    def execute_trade(self, signal):
        # Your trading logic
        entry_price = self.get_current_price()
        position = self.open_position(signal)
        
        # ... wait for exit ...
        
        exit_price = self.get_current_price()
        pnl = self.calculate_pnl(entry_price, exit_price, position)
        
        # Record with optimizer
        self.optimizer.record_trade_result(
            strategy_name="my_strategy",
            trade_result={
                'pnl': pnl,
                'return_pct': pnl / (entry_price * position['size']),
                'fees': position['fees'],
                'duration_minutes': position['duration']
            }
        )
    
    def get_status(self):
        return self.optimizer.get_status()
```

### Use Case 2: Backtesting with Optimization

```python
from bot.auto_optimization_engine import get_auto_optimizer

def backtest_with_optimization(historical_data):
    optimizer = get_auto_optimizer()
    
    for trade in historical_data:
        # Simulate trade
        result = execute_backtest_trade(trade)
        
        # Record result
        optimizer.record_trade_result("backtest_strategy", result)
    
    # Trigger optimization after backtest
    cycle_id = optimizer.trigger_optimization("backtest_complete")
    
    # Get optimized parameters
    status = optimizer.get_status()
    optimized_params = status['active_parameters']
    
    return optimized_params
```

### Use Case 3: Multi-Strategy Portfolio

```python
from bot.auto_optimization_engine import get_auto_optimizer

optimizer = get_auto_optimizer()

# Record trades from multiple strategies
strategies = ['momentum', 'mean_reversion', 'breakout']

for strategy_name in strategies:
    for trade in get_strategy_trades(strategy_name):
        optimizer.record_trade_result(
            strategy_name=strategy_name,
            trade_result=trade
        )

# Optimizer tracks all strategies independently
# Can optimize each one separately
```

---

## Performance Tracking

### View Current Performance

```python
metrics = optimizer.current_metrics

print(f"""
Current Performance:
==================
Win Rate:      {metrics.win_rate:.1%}
Profit Factor: {metrics.profit_factor:.2f}
Sharpe Ratio:  {metrics.sharpe_ratio:.2f}
Sortino Ratio: {metrics.sortino_ratio:.2f}
Max Drawdown:  {metrics.max_drawdown:.1%}
Performance:   {metrics.performance_score:.1f}/100
""")
```

### Track Performance Over Time

```python
# Get historical metrics
history = list(optimizer.metrics_history)

# Plot performance over time
scores = [m.performance_score for m in history]
sharpes = [m.sharpe_ratio for m in history]
win_rates = [m.win_rate for m in history]

# Use your favorite plotting library
import matplotlib.pyplot as plt

plt.plot(scores, label='Performance Score')
plt.xlabel('Time')
plt.ylabel('Score')
plt.title('Performance Evolution')
plt.legend()
plt.show()
```

---

## Manual Controls

### Trigger Optimization Manually

```python
# Force an optimization cycle right now
cycle_id = optimizer.trigger_optimization(reason="manual")

print(f"Started optimization cycle: {cycle_id}")

# Wait for it to complete (or check later)
import time
while optimizer.state != "monitoring":
    time.sleep(5)
    print(f"State: {optimizer.state.value}")

print("Optimization complete!")
```

### Check Next Scheduled Optimization

```python
status = optimizer.get_status()
next_opt = status['next_scheduled_optimization']

if next_opt:
    print(f"Next optimization scheduled for: {next_opt}")
else:
    print("No optimization scheduled yet")
```

### View Optimization History

```python
print("Recent Optimization Cycles:")
print("=" * 60)

for cycle in optimizer.optimization_cycles[-5:]:  # Last 5
    status_icon = "✅" if cycle.was_deployed else "❌"
    
    print(f"\n{status_icon} {cycle.cycle_id}")
    print(f"   Trigger: {cycle.trigger_reason}")
    print(f"   Duration: {cycle.duration_minutes:.1f} minutes")
    print(f"   Improvement: {cycle.improvement_pct:+.1f}%")
    print(f"   Status: {cycle.status}")
```

---

## Troubleshooting Quick Reference

### Problem: No optimization happening

**Check:**
```python
status = optimizer.get_status()
print(f"Trades: {status['total_trades_tracked']}")
print(f"Required: {optimizer.min_trades_before_optimization}")
```

**Solution:**
```python
# Lower threshold or wait for more trades
optimizer.min_trades_before_optimization = 50
```

### Problem: Optimizations rejected

**Check:**
```python
last_cycle = optimizer.optimization_cycles[-1]
print(f"Improvement: {last_cycle.improvement_pct}%")
print(f"Required: {optimizer.min_improvement_for_deployment}%")
```

**Solution:**
```python
# Lower deployment threshold
optimizer.min_improvement_for_deployment = 3.0
```

### Problem: State file errors

**Solution:**
```python
# Reset state (WARNING: loses history)
import os
state_file = "./data/optimization/optimization_state.json"
if os.path.exists(state_file):
    os.remove(state_file)

# Recreate optimizer
optimizer = get_auto_optimizer()
```

---

## Integration Checklist

- [ ] Initialize optimizer (standalone or with NIJA Brain)
- [ ] Record every trade with `record_trade_result()`
- [ ] Include all required fields (pnl, return_pct, fees)
- [ ] Monitor status periodically with `get_status()`
- [ ] Wait for at least 100 trades before first optimization
- [ ] Review optimization cycles when they complete
- [ ] Trust the system - let it run automatically

---

## Next Steps

Once you're comfortable with the basics:

1. **Read the full documentation**: [AUTO_OPTIMIZATION_ENGINE.md](AUTO_OPTIMIZATION_ENGINE.md)
2. **Customize configuration** for your use case
3. **Monitor performance** over weeks/months
4. **Review optimization history** to understand improvements
5. **Integrate with your trading strategies**

---

## Key Takeaways

✅ **Simple to use** - Just `get_auto_optimizer()` and `record_trade_result()`  
✅ **Automatic** - Runs in background, no manual work needed  
✅ **Safe** - Multiple validation layers, automatic rollback  
✅ **Effective** - Uses cutting-edge AI optimization algorithms  

**The longer it runs, the better your bot performs.**

---

**Questions? Check the [full documentation](AUTO_OPTIMIZATION_ENGINE.md) for detailed information.**

*NIJA Trading Systems - January 30, 2026*
