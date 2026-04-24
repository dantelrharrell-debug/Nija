# NIJA Auto-Optimization Engine

## 🤖 Self-Improving AI Control Loop

The Auto-Optimization Engine is NIJA's most advanced feature: a completely autonomous system that continuously monitors performance, detects degradation, and automatically improves trading parameters without human intervention.

**This is the holy grail of algorithmic trading: a bot that gets better over time, automatically.**

---

## 🎯 Core Concept

Traditional trading bots require manual parameter tuning. NIJA's Auto-Optimization Engine creates a **continuous feedback loop**:

```
┌─────────────────────────────────────────────────────────┐
│                  CONTINUOUS LOOP                         │
│                                                          │
│  Trade → Measure → Learn → Optimize → Test → Deploy    │
│     ↑                                              ↓     │
│     └──────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

### The Process

1. **Monitor** - Tracks every trade and calculates performance metrics
2. **Detect** - Identifies performance degradation or optimization opportunities
3. **Optimize** - Uses AI algorithms to find better parameters
4. **Validate** - Tests new parameters on out-of-sample data
5. **Deploy** - Automatically updates parameters if improvement is significant
6. **Repeat** - Continuous cycle that never stops improving

---

## 🔥 Key Features

### 1. **Automatic Performance Monitoring**
- Real-time tracking of 15+ performance metrics
- Sharpe Ratio, Sortino Ratio, Win Rate, Profit Factor
- Drawdown monitoring and risk metrics
- Composite performance scoring (0-100)

### 2. **Intelligent Trigger System**
The engine automatically triggers optimization when:
- **Scheduled**: Weekly optimization cycles (configurable)
- **Performance Degradation**: >10% drop in performance score
- **Manual**: User-initiated optimization on demand

### 3. **Multi-Algorithm Optimization**
Uses state-of-the-art AI techniques:
- **Genetic Algorithms** - Evolutionary parameter search
- **Bayesian Optimization** - Efficient exploration of parameter space
- **Reinforcement Learning** - Learns from live trading feedback
- **Walk-Forward Validation** - Prevents overfitting

### 4. **Safe Deployment**
Built-in safety mechanisms:
- Out-of-sample testing before deployment
- Overfitting detection (efficiency ratio < 70% = reject)
- Minimum improvement threshold (5% default)
- Automatic rollback on performance degradation
- Gradual parameter updates

### 5. **Complete State Persistence**
- All optimization cycles saved to disk
- Parameter history tracking
- Recovery from crashes/restarts
- Audit trail for all changes

---

## 📊 Performance Metrics Tracked

### Risk-Adjusted Returns
- **Sharpe Ratio** (30% weight) - Return per unit of risk
- **Sortino Ratio** (15% weight) - Return per unit of downside risk
- **Max Drawdown** (15% weight) - Worst peak-to-trough decline

### Trading Efficiency
- **Win Rate** (20% weight) - Percentage of profitable trades
- **Profit Factor** (20% weight) - Gross profit / Gross loss
- **Average Win vs Loss** - Risk/reward balance

### Risk Metrics
- **Volatility** - Standard deviation of returns
- **VaR 95%** - Value at Risk (95th percentile)
- **Capital Efficiency** - Returns per dollar deployed

### Operational Metrics
- **Trades per Day** - Activity level
- **Avg Trade Duration** - Holding period efficiency
- **Risk-Adjusted Return** - Overall quality score

---

## 🚀 Quick Start

### Basic Integration

```python
from bot.auto_optimization_engine import get_auto_optimizer

# Initialize the engine
optimizer = get_auto_optimizer(
    state_dir="./data/optimization",
    config={
        'optimization_interval_hours': 168,  # Weekly
        'min_trades_before_optimization': 100,
        'degradation_threshold_pct': -10.0,  # -10%
        'min_improvement_for_deployment': 5.0  # +5%
    }
)

# Record every trade
optimizer.record_trade_result(
    strategy_name="apex_v72",
    trade_result={
        'pnl': 125.50,
        'return_pct': 0.025,  # 2.5%
        'fees': 2.50,
        'duration_minutes': 45
    }
)

# Check status anytime
status = optimizer.get_status()
print(f"Current Score: {status['current_performance_score']:.2f}")
print(f"State: {status['state']}")

# Trigger manual optimization
cycle_id = optimizer.trigger_optimization(reason="manual")
print(f"Started optimization cycle: {cycle_id}")
```

### Integration with NIJA Brain

The Auto-Optimization Engine is automatically integrated with NIJA Brain:

```python
from core.nija_brain import create_nija_brain

# NIJA Brain automatically initializes auto-optimizer
brain = create_nija_brain(
    total_capital=10000.0,
    config={
        'auto_optimization': {
            'optimization_interval_hours': 168,
            'min_trades_before_optimization': 100
        }
    }
)

# All trades automatically fed to optimizer
brain.record_trade_completion({
    'trade_id': 'trade_123',
    'strategy_id': 'apex_v72',
    'symbol': 'BTC-USD',
    'side': 'long',
    'pnl': 150.00,
    'return_pct': 0.03,
    'fees': 3.00,
    # ... other trade data
})

# Optimizer runs automatically in background
# No manual intervention needed!
```

---

## ⚙️ Configuration Options

### Core Settings

```python
config = {
    # Optimization schedule
    'optimization_interval_hours': 168,  # How often to run scheduled optimization
    
    # Data requirements
    'min_trades_before_optimization': 100,  # Minimum trades needed
    
    # Performance monitoring
    'performance_check_interval_hours': 24,  # How often to check performance
    'degradation_threshold_pct': -10.0,  # Trigger optimization if this bad
    
    # Deployment criteria
    'min_improvement_for_deployment': 5.0,  # Minimum % improvement to deploy
    'overfitting_threshold': 0.70,  # Out-sample / In-sample minimum ratio
    
    # State management
    'state_dir': './data/optimization',  # Where to store state
    'save_history_length': 10  # How many cycles to keep in history
}
```

### Optimization Algorithm Settings

```python
# Genetic algorithm config
genetic_config = {
    'population_size': 50,
    'num_generations': 20,
    'mutation_rate': 0.1,
    'crossover_rate': 0.7,
    'elitism_rate': 0.1
}

# Bayesian optimization config
bayesian_config = {
    'n_calls': 100,
    'n_initial_points': 10,
    'acq_func': 'EI',  # Expected Improvement
    'xi': 0.01,
    'kappa': 1.96
}

# Walk-forward config
walkforward_config = {
    'train_window_days': 90,
    'test_window_days': 30,
    'step_days': 30,
    'min_windows': 5
}
```

---

## 📈 Optimization States

The engine operates in different states:

### State Machine

```
IDLE → MONITORING → ANALYZING → OPTIMIZING → TESTING → DEPLOYING → MONITORING
                        ↓                                    ↓
                   ROLLING_BACK ← ← ← ← ← ← ← ← ← ← ← ← ← ←
```

### State Descriptions

- **IDLE** - Engine initialized but not active
- **MONITORING** - Actively tracking performance
- **ANALYZING** - Evaluating whether optimization is needed
- **OPTIMIZING** - Running AI algorithms to find better parameters
- **TESTING** - Validating candidates on out-of-sample data
- **DEPLOYING** - Applying new parameters to production
- **ROLLING_BACK** - Reverting to previous parameters (if new ones fail)

---

## 🔍 Monitoring & Reporting

### Get Current Status

```python
status = optimizer.get_status()

# Returns:
{
    'state': 'monitoring',
    'current_performance_score': 78.5,
    'baseline_performance_score': 72.3,
    'total_trades_tracked': 247,
    'optimization_cycles_completed': 3,
    'active_parameters': {
        'apex_v72': 'param_20260130_143022'
    },
    'current_cycle': None,
    'next_scheduled_optimization': '2026-02-06T14:30:00'
}
```

### Performance Metrics

```python
metrics = optimizer.current_metrics

print(f"Win Rate: {metrics.win_rate:.1%}")
print(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
print(f"Profit Factor: {metrics.profit_factor:.2f}")
print(f"Max Drawdown: {metrics.max_drawdown:.1%}")
print(f"Performance Score: {metrics.performance_score:.1f}/100")
```

### Optimization History

```python
# Get last 5 optimization cycles
recent_cycles = optimizer.optimization_cycles[-5:]

for cycle in recent_cycles:
    print(f"Cycle: {cycle.cycle_id}")
    print(f"  Trigger: {cycle.trigger_reason}")
    print(f"  Improvement: {cycle.improvement_pct:.1f}%")
    print(f"  Deployed: {cycle.was_deployed}")
    print(f"  Duration: {cycle.duration_minutes:.1f} minutes")
```

---

## 🛡️ Safety Features

### 1. Overfitting Prevention

**Walk-Forward Validation**
- Parameters tested on unseen data
- Out-of-sample performance must be ≥70% of in-sample
- Automatic rejection of overfit parameters

**Efficiency Ratio**
```python
efficiency_ratio = out_sample_score / in_sample_score

if efficiency_ratio < 0.70:
    # Parameter set rejected - likely overfit
    reject_candidate()
```

### 2. Minimum Improvement Threshold

New parameters must show significant improvement:

```python
improvement = (new_score - baseline_score) / baseline_score * 100

if improvement < 5.0:  # Less than 5% improvement
    # Not worth the risk of changing parameters
    reject_candidate()
```

### 3. Automatic Rollback

If deployed parameters underperform:

1. Monitor performance for 24-48 hours after deployment
2. Compare to baseline metrics
3. If degradation > 15%, automatically rollback
4. Restore previous parameter set
5. Mark optimization cycle as "rolled_back"

### 4. State Recovery

Complete crash recovery:
- All state saved to disk after every cycle
- Automatic reload on restart
- No data loss even after crashes
- Audit trail preserved

---

## 🎓 Advanced Usage

### Custom Performance Scoring

Override the default performance score calculation:

```python
from bot.auto_optimization_engine import OptimizationMetrics

class CustomMetrics(OptimizationMetrics):
    def calculate_performance_score(self) -> float:
        # Custom scoring logic
        score = (
            self.sharpe_ratio * 0.40 +  # More weight on Sharpe
            self.profit_factor * 0.30 +
            self.win_rate * 0.30
        )
        self.performance_score = max(score, 0.0)
        return self.performance_score
```

### Manual Parameter Override

Force specific parameters (override optimization):

```python
from bot.auto_optimization_engine import ParameterSet
from datetime import datetime

# Create custom parameter set
custom_params = ParameterSet(
    parameter_id="manual_override_001",
    strategy_name="apex_v72",
    parameters={
        'rsi_period': 14,
        'rsi_oversold': 25,
        'rsi_overbought': 75,
        'stop_loss_pct': 0.02,
        'profit_target_pct': 0.06
    }
)

# Deploy immediately (skip optimization)
optimizer._deploy_candidate(custom_params)
```

### Integration with Custom Strategies

```python
from bot.auto_optimization_engine import get_auto_optimizer

class MyCustomStrategy:
    def __init__(self):
        self.optimizer = get_auto_optimizer()
        
    def apply_parameters(self, params):
        """Apply optimized parameters to strategy"""
        for param_name, value in params.items():
            setattr(self, param_name, value)
    
    def on_trade_complete(self, result):
        """Record trade with optimizer"""
        self.optimizer.record_trade_result(
            strategy_name="my_custom_strategy",
            trade_result=result
        )
        
        # Check if new optimized parameters available
        status = self.optimizer.get_status()
        active_params = status['active_parameters'].get('my_custom_strategy')
        
        if active_params and active_params != self.current_params:
            # New parameters deployed - update strategy
            new_params = self.optimizer.active_parameters['my_custom_strategy']
            self.apply_parameters(new_params.parameters)
            print(f"🔄 Updated to new parameters: {active_params}")
```

---

## 📊 Example Optimization Cycle

Let's walk through a complete optimization cycle:

### 1. Performance Monitoring (Day 1-7)

```
Trading with baseline parameters...
- Win Rate: 62%
- Sharpe: 1.8
- Profit Factor: 2.1
- Performance Score: 72.5/100
```

### 2. Trigger Detection (Day 7)

```
⏰ Scheduled optimization trigger (168h since last)
🚀 Starting optimization cycle opt_20260130_140000
   Reason: scheduled
   Baseline score: 72.5
```

### 3. Optimization Phase (Minutes 0-30)

```
🔬 Running optimization algorithms...
✅ Meta-optimizer found candidate with score: 68.2
🧬 Running genetic evolution...
   Generation 1: Best fitness 70.1
   Generation 5: Best fitness 74.8
   Generation 10: Best fitness 78.2
   Generation 20: Best fitness 79.5
✅ Genetic algorithm converged: 79.5
```

### 4. Validation Phase (Minutes 30-45)

```
🧪 Testing candidate parameters: param_20260130_140030
📊 Running walk-forward validation...
   Window 1: In-sample 78.2, Out-sample 72.5
   Window 2: In-sample 79.8, Out-sample 75.1
   Window 3: In-sample 78.9, Out-sample 73.8
   Average efficiency ratio: 0.92
✅ Candidate approved! Improvement: 9.7%
```

### 5. Deployment (Minutes 45-46)

```
🚀 Deploying new parameters: param_20260130_140030
   New baseline score: 73.3
✅ Deployment complete!
📝 Optimization cycle finalized: completed
```

### 6. Post-Deployment Monitoring (Days 8-14)

```
Monitoring new parameters...
- Win Rate: 65% (+3%)
- Sharpe: 2.0 (+11%)
- Profit Factor: 2.4 (+14%)
- Performance Score: 79.8/100 (+10%)

✅ Parameters performing as expected
```

---

## 🔧 Troubleshooting

### Optimization Never Triggers

**Symptom**: Optimizer stays in MONITORING state forever

**Solution**:
```python
# Check requirements
status = optimizer.get_status()
print(f"Trades: {status['total_trades_tracked']}")
print(f"Required: {optimizer.min_trades_before_optimization}")

# If not enough trades, lower threshold
optimizer.min_trades_before_optimization = 50

# Or trigger manually
optimizer.trigger_optimization("manual")
```

### All Candidates Rejected

**Symptom**: Optimization runs but never deploys

**Possible Causes**:
1. **Overfitting** - Out-sample performance < 70% of in-sample
2. **Insufficient improvement** - Less than 5% better
3. **Bad optimization** - Algorithm not finding good parameters

**Solution**:
```python
# Lower deployment threshold
optimizer.min_improvement_for_deployment = 2.0  # Accept 2%

# Lower overfitting threshold
optimizer.config['overfitting_threshold'] = 0.60  # Accept 60%

# Or check what's happening
last_cycle = optimizer.optimization_cycles[-1]
print(f"Best score: {last_cycle.best_candidate_score}")
print(f"Baseline: {last_cycle.baseline_metrics.performance_score}")
print(f"Status: {last_cycle.status}")
print(f"Notes: {last_cycle.notes}")
```

### Performance Degradation After Deployment

**Symptom**: New parameters perform worse than expected

**Solution**:
The engine should auto-rollback, but you can force it:

```python
# Get previous parameters
previous_params = [p for p in optimizer.parameter_history 
                   if p.retired_at is not None][-1]

# Redeploy previous parameters
optimizer._deploy_candidate(previous_params)

# Mark cycle as rolled back
if optimizer.current_cycle:
    optimizer.current_cycle.status = "rolled_back"
```

---

## 📚 Technical Details

### Performance Score Formula

```python
score = (
    sharpe_score * 0.30 +      # Sharpe Ratio (normalized to 0-100)
    win_rate_score * 0.20 +    # Win Rate * 100
    pf_score * 0.20 +          # Profit Factor (normalized)
    dd_score * 0.15 +          # Drawdown penalty
    sortino_score * 0.15       # Sortino Ratio (normalized)
)
```

Where:
- `sharpe_score = min(sharpe_ratio * 20, 100)` - Sharpe 5.0 = 100 points
- `win_rate_score = win_rate * 100` - Direct percentage
- `pf_score = min((profit_factor - 1) * 33.33, 100)` - PF 4.0 = 100 points
- `dd_score = max(100 - abs(max_drawdown) * 200, 0)` - Penalize drawdown
- `sortino_score = min(sortino_ratio * 20, 100)` - Sortino 5.0 = 100 points

### State Persistence Format

Saved to `./data/optimization/optimization_state.json`:

```json
{
  "current_metrics": {
    "timestamp": "2026-01-30T14:30:00",
    "total_trades": 247,
    "win_rate": 0.62,
    "sharpe_ratio": 1.8,
    "performance_score": 72.5
  },
  "baseline_metrics": { ... },
  "active_parameters": {
    "apex_v72": {
      "parameter_id": "param_20260130_140030",
      "parameters": { ... },
      "deployed_at": "2026-01-30T14:40:30"
    }
  },
  "optimization_cycles": [ ... ],
  "last_updated": "2026-01-30T14:45:00"
}
```

---

## 🎯 Best Practices

### 1. Let It Run Long Enough

- Minimum 100 trades before first optimization
- Weekly optimization cycles recommended
- Don't trigger manual optimization too often

### 2. Monitor the Monitoring

- Check status daily: `optimizer.get_status()`
- Review cycle history weekly
- Watch for degradation patterns

### 3. Trust the System

- Don't override unless absolutely necessary
- Let automatic rollback handle failures
- Give new parameters 1-2 weeks to prove themselves

### 4. Integration Tips

- Record ALL trades (even losses)
- Include accurate fees and slippage
- Provide complete trade data (duration, MFE, MAE)

### 5. Configuration Tuning

Start conservative, get aggressive over time:

```python
# Conservative (recommended for start)
config = {
    'optimization_interval_hours': 336,  # Every 2 weeks
    'min_trades_before_optimization': 200,
    'min_improvement_for_deployment': 10.0,  # 10% minimum
    'degradation_threshold_pct': -15.0  # Allow more variance
}

# Aggressive (after proven stable)
config = {
    'optimization_interval_hours': 168,  # Weekly
    'min_trades_before_optimization': 100,
    'min_improvement_for_deployment': 5.0,  # 5% minimum
    'degradation_threshold_pct': -10.0  # Trigger sooner
}
```

---

## 🚀 Future Enhancements

Planned features for future releases:

1. **Multi-Objective Optimization**
   - Pareto frontier for risk vs return
   - Custom objective functions
   - User-defined optimization goals

2. **Ensemble Parameter Sets**
   - Run multiple parameter sets simultaneously
   - Dynamic allocation based on market conditions
   - Diversity maintenance

3. **Market Regime Awareness**
   - Different parameters for different regimes
   - Automatic regime detection
   - Regime-specific optimization

4. **Online Learning**
   - Real-time parameter updates
   - Continuous micro-adjustments
   - No full re-optimization needed

5. **Distributed Optimization**
   - Cloud-based parameter search
   - Parallel backtesting
   - Faster optimization cycles

---

## 💡 Summary

The Auto-Optimization Engine is the ultimate "set and forget" feature:

✅ **Automatic** - No manual intervention required  
✅ **Safe** - Multiple layers of validation and rollback  
✅ **Intelligent** - Uses cutting-edge AI algorithms  
✅ **Transparent** - Complete audit trail and reporting  
✅ **Persistent** - Survives crashes and restarts  

**This is how you create a trading bot that improves itself over time.**

The longer it runs, the better it gets. This is the future of algorithmic trading.

---

## 📞 Support

Questions or issues?

1. Check the [Auto-Optimization Quickstart](AUTO_OPTIMIZATION_QUICKSTART.md)
2. Review troubleshooting section above
3. Check logs in `./data/optimization/`
4. Review state file for debugging

---

**Built with ❤️ by NIJA Trading Systems**

*Version 1.0 - January 30, 2026*
