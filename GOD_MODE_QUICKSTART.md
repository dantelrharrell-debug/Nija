# NIJA God Mode - Quick Start Guide

## 🚀 Getting Started in 5 Minutes

This guide gets you up and running with God Mode fast.

## Prerequisites

Ensure you have all dependencies installed:
```bash
pip install -r requirements.txt
```

Required packages:
- numpy
- pandas
- Python 3.11+

## Quick Start

### 1. Import God Mode

```python
from bot.god_mode_engine import GodModeEngine, GodModeConfig
from bot.god_mode_config import GOD_MODE_CONFIG
```

### 2. Initialize

```python
# Use default configuration
config = GodModeConfig(**GOD_MODE_CONFIG)
god_mode = GodModeEngine(config)

# Or customize
config = GodModeConfig(
    enable_bayesian_regime=True,
    enable_meta_optimizer=True,
    enable_walk_forward=False,  # Disable if not backtesting
    enable_risk_parity=True,
    enable_live_rl=True,
)
god_mode = GodModeEngine(config)
```

### 3. Get Trading Recommendation

```python
# Get recommendation for current market
recommendation = god_mode.get_recommendation(
    market_data=df,        # Your OHLCV DataFrame
    indicators=indicators,  # Your technical indicators dict
)

# Access recommendations
print(recommendation.summary)
strategy_id = recommendation.recommended_strategy_id
params = recommendation.recommended_parameters
regime = recommendation.market_regime
```

### 4. Use Recommended Parameters

```python
# Apply recommended parameters to your strategy
min_signal_score = params.get('min_signal_score', 3.0)
min_adx = params.get('min_adx', 20.0)
atr_stop_multiplier = params.get('atr_stop_multiplier', 1.5)

# Use in your entry logic
if signal_score >= min_signal_score and adx >= min_adx:
    enter_trade()
```

### 5. Record Trades for Learning

```python
# When entering a trade
god_mode.record_trade_entry(
    trade_id="BTCUSD_12345",
    market_data=df,
    indicators=indicators,
    strategy_used=strategy_id,
    entry_price=45000.00,
    parameters_used=params,
)

# When exiting a trade
god_mode.record_trade_exit(
    trade_id="BTCUSD_12345",
    market_data=df,
    indicators=indicators,
    exit_price=45500.00,
    profit_loss=500.00,
    parameters_used=params,
)
```

### 6. Save State (Auto or Manual)

```python
# Auto-save is enabled by default (every 10 trades)
# Or save manually
god_mode.save_state()

# Load on next startup
god_mode.load_state()
```

## Configuration Presets

### Conservative (Lower Risk)
```python
from bot.god_mode_config import CONSERVATIVE_GOD_MODE_CONFIG

config = GodModeConfig(**CONSERVATIVE_GOD_MODE_CONFIG)
god_mode = GodModeEngine(config)
```

### Aggressive (Higher Risk/Reward)
```python
from bot.god_mode_config import AGGRESSIVE_GOD_MODE_CONFIG

config = GodModeConfig(**AGGRESSIVE_GOD_MODE_CONFIG)
god_mode = GodModeEngine(config)
```

### Custom
```python
config = GodModeConfig(
    # Enable only specific features
    enable_bayesian_regime=True,
    enable_meta_optimizer=True,
    enable_walk_forward=False,
    enable_risk_parity=True,
    enable_live_rl=False,
    
    # Customize sub-configs
    bayesian_config={
        'prior_trending': 0.40,  # Expect more trending markets
        'transition_threshold': 0.15,
    },
    risk_parity_config={
        'target_portfolio_vol': 0.12,  # 12% target volatility
        'max_position_size': 0.15,     # 15% max per position
    },
)
```

## Integration with Existing Strategy

### Option 1: Enhance Existing Strategy

```python
class MyStrategy:
    def __init__(self, broker_client):
        self.broker = broker_client
        
        # Add God Mode
        from bot.god_mode_engine import GodModeEngine, GodModeConfig
        from bot.god_mode_config import GOD_MODE_CONFIG
        
        config = GodModeConfig(**GOD_MODE_CONFIG)
        self.god_mode = GodModeEngine(config)
    
    def should_enter(self, symbol, df, indicators):
        # Get God Mode recommendation
        rec = self.god_mode.get_recommendation(df, indicators)
        
        # Use recommended parameters
        params = rec.recommended_parameters
        min_score = params.get('min_signal_score', 3)
        
        # Your existing logic with God Mode params
        signal_score = self.calculate_signal_score(df, indicators)
        
        return signal_score >= min_score
```

### Option 2: Standalone God Mode Trading

```python
def main_trading_loop():
    god_mode = initialize_god_mode()
    
    while True:
        # Get current market data
        df = fetch_market_data()
        indicators = calculate_indicators(df)
        
        # Get God Mode recommendation
        rec = god_mode.get_recommendation(df, indicators)
        
        # Execute based on recommendation
        if should_enter(rec):
            trade_id = execute_entry(rec)
            god_mode.record_trade_entry(...)
        
        # Check exits
        for trade in open_trades:
            if should_exit(trade):
                execute_exit(trade)
                god_mode.record_trade_exit(...)
        
        time.sleep(60)  # Check every minute
```

## What Each Feature Does

### 🎲 Bayesian Regime Detection
- **Output:** Market regime (Trending/Ranging/Volatile) with probabilities
- **Use:** Adapt strategy to market conditions
- **Access:** `recommendation.market_regime`, `recommendation.regime_probabilities`

### 🧠 Meta-Learning Optimizer
- **Output:** Optimized strategy parameters
- **Use:** Automatically tune parameters based on performance
- **Access:** `recommendation.recommended_parameters`

### 🚶 Walk-Forward Optimization
- **Output:** Validated parameters (use in backtesting phase)
- **Use:** Find parameters that work out-of-sample
- **Access:** Run separately during optimization phase

### ⚖️ Risk Parity Allocation
- **Output:** Position size recommendations
- **Use:** Size positions based on risk, not capital
- **Access:** `recommendation.recommended_position_sizes`

### 🤖 Live RL Feedback
- **Output:** Strategy selection
- **Use:** Select best strategy for current conditions
- **Access:** `recommendation.recommended_strategy_id`

## Monitoring

Check God Mode status:

```python
# Meta-optimizer status
if god_mode.meta_optimizer:
    status = god_mode.meta_optimizer.get_status()
    print(status.summary)

# RL status
if god_mode.live_rl:
    rl_status = god_mode.live_rl.get_status()
    print(rl_status.summary)

# Bayesian regime
if god_mode.bayesian_regime:
    # Priors are updated automatically
    print(f"Current regime: {god_mode.bayesian_regime.current_regime}")
```

## Common Patterns

### Pattern 1: Parameter Adaptation
```python
# God Mode automatically adapts parameters
for day in trading_days:
    rec = god_mode.get_recommendation(df, indicators)
    params = rec.recommended_parameters  # Different each day!
    trade_with_params(params)
```

### Pattern 2: Regime-Based Strategy Selection
```python
rec = god_mode.get_recommendation(df, indicators)

if rec.market_regime == "trending":
    use_trend_following_strategy()
elif rec.market_regime == "ranging":
    use_mean_reversion_strategy()
else:  # volatile
    reduce_position_sizes()
```

### Pattern 3: Risk Parity Portfolio
```python
rec = god_mode.get_recommendation(
    df, indicators,
    current_positions=portfolio,
    price_history=price_data,
)

# Rebalance if needed
if rec.risk_parity_adjustment:
    for symbol, target_size in rec.recommended_position_sizes.items():
        rebalance_position(symbol, target_size)
```

## Troubleshooting

### "Module not found" errors
```bash
pip install -r requirements.txt
```

### State not saving
Check directory permissions:
```python
config = GodModeConfig(
    state_dir='./my_state',  # Ensure this directory is writable
    auto_save=True,
)
```

### Poor performance initially
God Mode needs data to learn:
- Allow 50-100 trades for RL to learn
- Meta-optimizer improves after 20+ parameter evaluations
- Bayesian priors update after ~100 regime observations

### Memory usage
Disable features you don't need:
```python
config = GodModeConfig(
    enable_walk_forward=False,  # Only for backtesting
    enable_risk_parity=False,   # If not managing portfolio
)
```

## Next Steps

1. ✅ Run the example: `python bot/god_mode_example.py`
2. 📚 Read full documentation: `GOD_MODE_DOCUMENTATION.md`
3. 🔧 Customize configuration: `bot/god_mode_config.py`
4. 🚀 Integrate with your strategy
5. 📊 Monitor performance and let it learn!

## Need Help?

- 📖 Full Documentation: `GOD_MODE_DOCUMENTATION.md`
- 💡 Examples: `bot/god_mode_example.py`
- ⚙️ Configuration: `bot/god_mode_config.py`

---

**Ready to activate God Mode? 🔥**

```python
from bot.god_mode_engine import GodModeEngine, GodModeConfig
from bot.god_mode_config import GOD_MODE_CONFIG

config = GodModeConfig(**GOD_MODE_CONFIG)
god_mode = GodModeEngine(config)

# You're now in God Mode! 🔥
```
