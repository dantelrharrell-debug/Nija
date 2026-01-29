# NIJA Brain - Integrated Intelligence System

## Overview

NIJA Brain is the central intelligence system that orchestrates all trading decisions through four integrated components:

1. **Multi-Strategy Orchestration** 🧠 - The Brain
2. **Execution Intelligence** 💰 - The Money Layer
3. **Self-Learning Engine** 📚 - Continuous Improvement
4. **Investor Metrics** 📊 - Institutional Analytics

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      NIJA BRAIN                          │
│                  Central Coordinator                     │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Strategy    │  │  Execution   │  │ Self-Learning│
│ Orchestrator │  │ Intelligence │  │   Engine     │
└──────────────┘  └──────────────┘  └──────────────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
                  ┌──────────────┐
                  │   Investor   │
                  │   Metrics    │
                  └──────────────┘
```

## Components

### 1. Multi-Strategy Orchestrator

**Location**: `core/strategy_orchestrator.py`

Manages multiple trading strategies simultaneously with:
- Dynamic strategy selection based on market regime
- Ensemble voting for high-confidence signals
- Adaptive capital allocation (Kelly Criterion)
- Real-time performance tracking
- Automatic strategy rotation

**Key Features**:
- Registers and manages multiple strategies (v7.1, v7.2, custom)
- Detects market regimes (trending, ranging, volatile)
- Allocates capital based on performance
- Requires 2+ strategies to agree before trading (ensemble voting)

**Example Usage**:
```python
from core.strategy_orchestrator import create_default_orchestrator

# Create orchestrator with $10,000 capital
orchestrator = create_default_orchestrator(10000.0)

# Get trading signals from all strategies
signals = orchestrator.get_trading_signals(symbol, df, indicators)

# Execute ensemble vote
consensus = orchestrator.execute_ensemble_vote(signals)

# Record trade result
orchestrator.record_trade_result(
    strategy_id="apex_v72",
    pnl=50.0,
    fees=0.50,
    regime="trending"
)
```

### 2. Execution Intelligence

**Location**: `core/execution_intelligence.py`

Optimizes profit extraction through:
- ML-based exit scoring
- Dynamic profit targets based on volatility
- Slippage detection and tracking
- Partial exit strategies
- Fill probability estimation

**Key Features**:
- Calculates optimal exit timing (0-100 score)
- Adjusts profit targets for market conditions
- Tracks execution quality (slippage, fees)
- Recommends partial exits vs full exits

**Example Usage**:
```python
from core.execution_intelligence import create_execution_intelligence

exec_intel = create_execution_intelligence()

# Evaluate exit opportunity
exit_signal = exec_intel.calculate_exit_score(symbol, df, indicators, position)

# Get dynamic profit targets
targets = exec_intel.get_dynamic_profit_targets(symbol, df, indicators, entry_price)

# Calculate optimal exit size
exit_size, reason = exec_intel.calculate_optimal_exit_size(position, exit_signal, balance)

# Track execution quality
exec_intel.track_execution(execution_metrics)
```

### 3. Self-Learning Engine

**Location**: `core/self_learning_engine.py`

Continuous improvement through:
- Trade performance analysis
- A/B testing for parameters
- Optimization suggestions
- Feature importance tracking
- Training data collection

**Key Features**:
- Records all trades for analysis
- Identifies optimal parameters from historical data
- Runs A/B tests on strategy variants
- Generates optimization suggestions
- Exports data for ML training

**Example Usage**:
```python
from core.self_learning_engine import create_learning_engine

learning = create_learning_engine('./data/learning')

# Record completed trade
learning.record_trade(trade_record)

# Analyze strategy performance
analysis = learning.analyze_strategy_performance('apex_v72', lookback_days=30)

# Start A/B test
test_id = learning.start_ab_test(
    strategy_id='apex_v72',
    parameter_name='min_confidence',
    control_value=0.65,
    test_value=0.75
)

# Get optimization suggestions
suggestions = learning.get_optimization_suggestions('apex_v72')
```

### 4. Investor Metrics Engine

**Location**: `core/investor_metrics.py`

Institutional-grade analytics:
- Sharpe, Sortino, Calmar ratios
- Drawdown analysis
- Trade attribution
- Strategy comparison
- Rolling metrics

**Key Features**:
- Calculates risk-adjusted returns
- Tracks drawdown periods
- Generates investor reports
- Compares strategy performance
- Provides rolling 30-day metrics

**Example Usage**:
```python
from core.investor_metrics import create_metrics_engine

metrics = create_metrics_engine(initial_capital=10000.0)

# Update equity after trade
metrics.update_equity(new_equity=10500.0, strategy_id='apex_v72')

# Get performance metrics
performance = metrics.get_performance_metrics(lookback_days=30)

# Compare strategies
comparison = metrics.get_strategy_comparison()

# Generate investor report
report = metrics.generate_investor_report()
```

## Integrated Usage (NIJA Brain)

**Location**: `core/nija_brain.py`

The Brain coordinates all components:

```python
from core.nija_brain import create_nija_brain

# Initialize NIJA Brain
brain = create_nija_brain(
    total_capital=10000.0,
    config={
        'execution': {'enable_dynamic_targets': True},
        'learning': {'min_trades_for_learning': 30},
        'metrics': {'risk_free_rate': 0.02}
    }
)

# Analyze trading opportunity
analysis = brain.analyze_opportunity(symbol, df, indicators)
# Returns: decision, confidence, multi-strategy consensus

# Evaluate exit for position
exit_eval = brain.evaluate_exit(symbol, df, indicators, position)
# Returns: should_exit, exit_pct, reason, score

# Record completed trade
brain.record_trade_completion(trade_data)
# Updates: learning engine, orchestrator, metrics

# Get comprehensive report
report = brain.get_performance_report()
# Includes: strategy performance, execution quality, learning insights, investor metrics

# Perform daily review
brain.perform_daily_review()
# Reviews strategies, generates optimization suggestions
```

## Configuration

### Strategy Orchestrator Config

```python
{
    'reserve_capital_pct': 0.20,  # 20% reserve
    'ensemble_voting_enabled': True,
    'ensemble_min_votes': 2,  # Minimum strategies that must agree
    'performance_review_interval': 3600  # 1 hour
}
```

### Execution Intelligence Config

```python
{
    'enable_dynamic_targets': True,
    'enable_partial_exits': True,
    'min_profit_for_exit': 0.005,  # 0.5%
    'slippage_threshold_bps': 10  # 10 basis points
}
```

### Self-Learning Config

```python
{
    'min_trades_for_learning': 30,
    'optimization_interval_hours': 24
}
```

### Investor Metrics Config

```python
{
    'risk_free_rate': 0.02  # 2% annual
}
```

## Performance Metrics

### Orchestrator Metrics
- Strategy win rates by regime
- Capital allocations
- Ensemble agreement rates
- Strategy state changes (active/monitoring/disabled)

### Execution Metrics
- Average slippage (basis points)
- Execution duration
- Fill quality
- Total execution costs

### Learning Metrics
- Trade quality scores
- Parameter performance
- A/B test results
- Optimization suggestions

### Investor Metrics
- Sharpe Ratio (risk-adjusted return)
- Sortino Ratio (downside risk)
- Calmar Ratio (return/max drawdown)
- Maximum drawdown
- Win rate and profit factor

## Integration with Existing NIJA

The Brain integrates with existing components:

1. **Strategies**: Registers v7.1, v7.2, and custom strategies
2. **Broker Integration**: Uses existing broker adapters
3. **Risk Management**: Coordinates with existing risk systems
4. **Position Management**: Enhances position sizing and exits

## Example Workflow

1. **Market Scan**: Brain analyzes opportunity
2. **Strategy Consensus**: Multiple strategies vote
3. **Entry Decision**: Ensemble decides if confidence is high enough
4. **Position Sizing**: Orchestrator allocates capital based on performance
5. **Position Monitoring**: Execution Intelligence tracks position
6. **Exit Optimization**: ML-based exit scoring
7. **Trade Recording**: All systems learn from result
8. **Performance Review**: Daily optimization and adjustment

## Benefits

### For Traders
- ✅ Higher win rates through ensemble voting
- ✅ Better exits through execution intelligence
- ✅ Continuous improvement through learning
- ✅ Multiple strategies working together

### For Investors
- ✅ Institutional-grade metrics (Sharpe, Sortino, Calmar)
- ✅ Transparent performance tracking
- ✅ Risk management (drawdown tracking)
- ✅ Strategy attribution and comparison

### For Development
- ✅ Modular architecture (easy to add strategies)
- ✅ A/B testing framework
- ✅ Data collection for ML training
- ✅ Performance feedback loop

## Files Created

```
core/
├── strategy_orchestrator.py      # Multi-strategy management
├── execution_intelligence.py     # Exit optimization
├── self_learning_engine.py       # Continuous learning
├── investor_metrics.py           # Institutional metrics
└── nija_brain.py                 # Central coordinator

examples/
└── nija_brain_example.py         # Usage examples
```

## Next Steps

1. **Integration**: Connect Brain to live trading loop
2. **Backtesting**: Test on historical data
3. **Monitoring**: Add real-time dashboards
4. **ML Models**: Train actual ML models for predictions
5. **API**: Expose Brain through API endpoints

## Security Notes

- Brain inherits security model from existing NIJA architecture
- Strategy logic remains in private core layer
- User permissions enforced through execution layer
- All API keys remain encrypted

## Version

- Version: 1.0
- Date: January 28, 2026
- Status: ✅ Core Implementation Complete

## Support

For questions or issues:
1. Check `examples/nija_brain_example.py` for usage
2. Review component documentation in source files
3. See `ARCHITECTURE.md` for system overview
