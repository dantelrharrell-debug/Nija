# 🔥 NIJA God Mode - True Quant-Research Level Trading

## Overview

NIJA God Mode integrates **five advanced quant-research features** into a unified, self-learning trading intelligence system. This represents the cutting edge of algorithmic trading technology.

## The Five Features

### 1️⃣ Bayesian Regime Probability Engine
- **Probabilistic** market regime detection (not binary)
- Confidence-weighted strategy parameters
- Adaptive priors based on observed market behavior
- Smooth regime transitions

**Code:** `bot/bayesian_regime_detector.py`

### 2️⃣ Meta-Learning Optimizer (Self-Tuning Parameters)
- **Automatically** tunes strategy parameters
- Learns from performance history
- Balances exploration vs exploitation
- Performance-weighted parameter ensembles

**Code:** `bot/meta_optimizer.py`

### 3️⃣ Walk-Forward Genetic Optimization
- Rolling window backtesting
- **Out-of-sample validation**
- Prevents overfitting
- Genetic algorithm parameter search

**Code:** `bot/walk_forward_optimizer.py`

### 4️⃣ Portfolio-Level Risk Parity & Correlation Control
- **Equal risk contribution** per position
- Volatility-based sizing
- Correlation-adjusted allocation
- True portfolio diversification

**Code:** `bot/risk_parity_allocator.py`

### 5️⃣ Live Reinforcement Learning Feedback Loop
- **Continuous learning** from live trades
- Q-learning strategy selection
- Real-time reward calculation
- Adaptive decision-making

**Code:** `bot/live_rl_feedback.py`

## Quick Start

```python
from bot.god_mode_engine import GodModeEngine, GodModeConfig
from bot.god_mode_config import GOD_MODE_CONFIG

# Initialize God Mode
config = GodModeConfig(**GOD_MODE_CONFIG)
god_mode = GodModeEngine(config)

# Get recommendation
recommendation = god_mode.get_recommendation(
    market_data=df,
    indicators=indicators,
)

# Use recommendations
params = recommendation.recommended_parameters
strategy = recommendation.recommended_strategy_id
regime = recommendation.market_regime

# Record trades for learning
god_mode.record_trade_entry(trade_id, market_data, indicators,
                             strategy, entry_price, params)
god_mode.record_trade_exit(trade_id, market_data, indicators,
                            exit_price, profit_loss, params)
```

## Files

| File | Purpose |
|------|---------|
| `bot/bayesian_regime_detector.py` | Bayesian regime probability engine |
| `bot/meta_optimizer.py` | Meta-learning parameter optimizer |
| `bot/walk_forward_optimizer.py` | Walk-forward genetic optimization |
| `bot/risk_parity_allocator.py` | Risk parity portfolio allocation |
| `bot/live_rl_feedback.py` | Live reinforcement learning loop |
| `bot/god_mode_engine.py` | **Master orchestration engine** |
| `bot/god_mode_config.py` | Configuration settings |
| `bot/god_mode_example.py` | Example usage |
| `GOD_MODE_DOCUMENTATION.md` | **Full documentation** |
| `GOD_MODE_QUICKSTART.md` | **Quick start guide** |

## Documentation

- 📚 **Full Documentation:** [GOD_MODE_DOCUMENTATION.md](GOD_MODE_DOCUMENTATION.md)
- 🚀 **Quick Start:** [GOD_MODE_QUICKSTART.md](GOD_MODE_QUICKSTART.md)
- 💡 **Examples:** `bot/god_mode_example.py`

## Performance Targets

| Metric | Target |
|--------|--------|
| Sharpe Ratio | 2.5+ |
| Win Rate | 65%+ |
| Profit Factor | 2.0+ |
| Max Drawdown | <15% |

## Key Advantages

✅ **Self-Optimizing:** Automatically tunes parameters based on performance  
✅ **Regime-Aware:** Adapts to changing market conditions  
✅ **Portfolio-Level:** True risk management across all positions  
✅ **Continuously Learning:** Improves from every trade  
✅ **Out-of-Sample Validated:** Prevents overfitting  
✅ **Production-Ready:** Designed for live trading  

## Architecture

```
God Mode Engine
├── Bayesian Regime Detector    → Probabilistic regime classification
├── Meta-Learning Optimizer      → Self-tuning parameters
├── Walk-Forward Optimizer       → Out-of-sample validation
├── Risk Parity Allocator        → Portfolio-level risk management
└── Live RL Feedback Loop        → Continuous learning
```

## Integration

Works seamlessly with existing NIJA components:

```python
# In your strategy:
class MyStrategy:
    def __init__(self):
        self.god_mode = GodModeEngine(config)

    def should_enter(self, df, indicators):
        rec = self.god_mode.get_recommendation(df, indicators)
        params = rec.recommended_parameters
        # Use recommended parameters
        return self.check_signals(params)
```

## Configuration Presets

- **Standard:** `GOD_MODE_CONFIG` - Balanced performance
- **Conservative:** `CONSERVATIVE_GOD_MODE_CONFIG` - Lower risk
- **Aggressive:** `AGGRESSIVE_GOD_MODE_CONFIG` - Higher risk/reward

## Requirements

```bash
pip install -r requirements.txt
```

- Python 3.11+
- numpy
- pandas
- Existing NIJA dependencies

## State Persistence

God Mode automatically saves learned knowledge:
- Meta-optimizer parameter performance
- RL Q-values and experience
- Bayesian regime priors

State saved to `./god_mode_state/` (configurable)

## Example Output

```
🔥 GOD MODE ACTIVATED - True Quant-Research Level Trading 🔥
Active Features:
  1️⃣ Bayesian Regime Probability: True
  2️⃣ Meta-Learning Optimizer: True
  3️⃣ Walk-Forward Genetic Optimization: True
  4️⃣ Risk Parity & Correlation Control: True
  5️⃣ Live Reinforcement Learning: True

📊 Regime: trending (confidence: 78%)
🧠 Parameters: ensemble
🤖 RL Strategy: 1 (confidence: 65%)
⚖️ Risk Parity: 3 positions sized
```

## Testing

Run example:
```bash
python bot/god_mode_example.py
```

Syntax validation:
```bash
python -m py_compile bot/god_mode_engine.py
```

## Theory

Based on cutting-edge quantitative research:
- **Bayesian Inference:** Probabilistic reasoning under uncertainty
- **Meta-Learning:** Learning to learn, algorithmic parameter search
- **Walk-Forward Analysis:** Industry-standard validation method
- **Risk Parity:** Equal risk contribution (Bridgewater Associates)
- **Reinforcement Learning:** Q-learning for optimal decision-making

## References

1. "Advances in Financial Machine Learning" - Marcos López de Prado
2. "Quantitative Trading" - Ernest Chan
3. Bridgewater Associates risk parity research
4. Renaissance Technologies quantitative methods
5. "Reinforcement Learning: An Introduction" - Sutton & Barto

## Contributing

To extend God Mode:
1. Add new features to `bot/meta_ai/`
2. Integrate in `god_mode_engine.py`
3. Update configuration
4. Document changes

## License

Part of the NIJA trading system.

## Support

- 📖 Read: `GOD_MODE_DOCUMENTATION.md`
- 🚀 Quick Start: `GOD_MODE_QUICKSTART.md`
- 💡 Examples: `bot/god_mode_example.py`
- ⚙️ Config: `bot/god_mode_config.py`

---

**God Mode: Because markets don't wait for manual parameter tuning. 🔥**

*Institutional-grade quantitative trading, automated.*
