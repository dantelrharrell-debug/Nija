# 🔥 NIJA AUTONOMOUS SCALING ENGINE 🔥

## Overview

The **NIJA Autonomous Scaling Engine** is an advanced capital management system that combines intelligent auto-scaling, risk-adjusted position sizing, volatility-based leverage, market regime allocation, and enhanced auto-compounding logic.

This extends the base Capital Scaling & Compounding Engine with autonomous decision-making capabilities that adapt to market conditions in real-time.

## 🚀 New Features

### 1. Git Metadata Injection
Automatically injects build-time Git information for version tracking:
- **GIT_BRANCH**: Current Git branch
- **GIT_COMMIT**: Full commit hash
- **GIT_COMMIT_SHORT**: Short commit hash
- **BUILD_TIMESTAMP**: ISO 8601 build timestamp

**Usage:**
```bash
# Run before building
bash inject_git_metadata.sh

# Or build with Docker (automatic)
docker build --build-arg GIT_BRANCH=$(git branch --show-current) \
             --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
             -t nija-bot .
```

### 2. Volatility-Based Leverage
Automatically adjusts position sizes based on market volatility:
- **Low Volatility** (<20%): Increases leverage up to 2.0x
- **Normal Volatility** (20-40%): Maintains standard leverage
- **High Volatility** (>40%): Reduces leverage down to 0.5x

**Formula:**
```python
leverage = (normal_vol / current_vol) ** sensitivity
position = base_position * clamp(leverage, min_leverage, max_leverage)
```

### 3. Market Regime Allocation
Adjusts capital allocation based on detected market conditions:

| Regime | Allocation | Description |
|--------|-----------|-------------|
| **Bull Trending** | 100% | Full allocation in strong uptrends |
| **Bear Trending** | 30% | Defensive allocation in downtrends |
| **Ranging** | 60% | Moderate allocation in sideways markets |
| **Volatile** | 40% | Reduced allocation in choppy conditions |
| **Crisis** | 10% | Minimal allocation, capital preservation |

### 4. Risk-Adjusted Position Sizing
Uses Sharpe ratio optimization to size positions:
```python
sharpe_ratio = (expected_return - risk_free_rate) / volatility
adjustment = sharpe_ratio / target_sharpe_ratio
position = base_position * clamp(adjustment, 0.3, 1.5)
```

### 5. Adaptive Auto-Compounding
Dynamically adjusts reinvestment based on performance:
- **High Performance** (>60% win rate): Increases reinvestment %
- **Normal Performance** (45-60% win rate): Maintains current %
- **Poor Performance** (<45% win rate): Decreases reinvestment %

### 6. Real-Time Parameter Optimization
Continuously optimizes parameters based on recent performance:
- Analyzes last 30 days of trades
- Adjusts regime allocations based on results
- Adapts volatility leverage sensitivity
- Requires minimum 20 trades for optimization

## 🎯 Quick Start

### Basic Usage

```python
from bot.autonomous_scaling_engine import get_autonomous_engine, MarketConditions, MarketRegime, VolatilityState

# Create autonomous engine
engine = get_autonomous_engine(
    base_capital=10000.0,
    compounding_strategy="moderate",
    enable_all_features=True
)

# Update market conditions
conditions = MarketConditions(
    volatility_pct=25.0,  # 25% annualized volatility
    trend_strength=0.7,  # Moderate bull trend
    regime=MarketRegime.BULL_TRENDING,
    volatility_state=VolatilityState.NORMAL,
    momentum_score=0.6,  # Positive momentum
    liquidity_score=0.9  # High liquidity
)

engine.update_market_conditions(conditions)

# Calculate optimal position size
available = 10000.0
position = engine.get_optimal_position_size(
    available_balance=available,
    expected_return=0.15,  # 15% expected annual return
    volatility=0.25  # 25% volatility
)

# Record a trade
engine.record_trade(
    profit=150.0,
    fees=5.0,
    is_win=True,
    new_capital=10145.0
)

# Get status
print(engine.get_quick_summary())
# Output: 💰 $10145.00 (+1.5% ROI) | ✅ TRADING | 🛡️ NORMAL | 🎯 Next: $25K (41%) | 📈 BULL_TRENDING | 🟡 Vol:25%
```

### Advanced Configuration

```python
from bot.autonomous_scaling_engine import AutonomousScalingEngine, AutonomousScalingConfig, CapitalEngineConfig

# Custom configurations
base_config = CapitalEngineConfig(
    compounding_strategy="aggressive",
    enable_drawdown_protection=True,
    halt_threshold_pct=25.0
)

autonomous_config = AutonomousScalingConfig(
    enable_volatility_leverage=True,
    min_leverage=0.3,
    max_leverage=3.0,
    volatility_leverage_sensitivity=1.2,

    enable_risk_adjustment=True,
    target_sharpe_ratio=2.5,

    enable_regime_allocation=True,
    regime_allocations={
        MarketRegime.BULL_TRENDING: 1.2,  # 120% in bull markets
        MarketRegime.BEAR_TRENDING: 0.2,  # 20% in bear markets
        MarketRegime.RANGING: 0.5,
        MarketRegime.VOLATILE: 0.3,
        MarketRegime.CRISIS: 0.1
    },

    enable_adaptive_compounding=True,
    enable_realtime_optimization=True,
    optimization_window_days=60
)

engine = AutonomousScalingEngine(
    base_capital=50000.0,
    base_config=base_config,
    autonomous_config=autonomous_config
)
```

## 📊 Market Regimes

### Detection Criteria

| Regime | Volatility | Trend Strength | Momentum | Conditions |
|--------|-----------|---------------|----------|------------|
| **Bull Trending** | Low-Normal | >+0.5 | >+0.4 | Clear uptrend, stable |
| **Bear Trending** | Normal-High | <-0.5 | <-0.4 | Clear downtrend |
| **Ranging** | Very Low-Low | -0.3 to +0.3 | -0.2 to +0.2 | Sideways movement |
| **Volatile** | High | Any | Any | High volatility, unpredictable |
| **Crisis** | Extreme | <-0.7 | <-0.6 | Market crash conditions |

### Example Detection

```python
def detect_market_regime(price_data, volume_data):
    """Detect current market regime from price/volume data"""

    # Calculate metrics
    volatility = calculate_annualized_volatility(price_data)
    trend = calculate_trend_strength(price_data)
    momentum = calculate_momentum(price_data)
    liquidity = calculate_liquidity(volume_data)

    # Classify volatility state
    if volatility < 10:
        vol_state = VolatilityState.VERY_LOW
    elif volatility < 20:
        vol_state = VolatilityState.LOW
    elif volatility < 40:
        vol_state = VolatilityState.NORMAL
    elif volatility < 60:
        vol_state = VolatilityState.HIGH
    else:
        vol_state = VolatilityState.EXTREME

    # Classify regime
    if volatility > 60 and trend < -0.7:
        regime = MarketRegime.CRISIS
    elif volatility > 40:
        regime = MarketRegime.VOLATILE
    elif trend > 0.5 and momentum > 0.4:
        regime = MarketRegime.BULL_TRENDING
    elif trend < -0.5 and momentum < -0.4:
        regime = MarketRegime.BEAR_TRENDING
    else:
        regime = MarketRegime.RANGING

    return MarketConditions(
        volatility_pct=volatility,
        trend_strength=trend,
        regime=regime,
        volatility_state=vol_state,
        momentum_score=momentum,
        liquidity_score=liquidity
    )
```

## 🎛️ Configuration Reference

### AutonomousScalingConfig

```python
@dataclass
class AutonomousScalingConfig:
    # Volatility-based leverage
    enable_volatility_leverage: bool = True
    min_leverage: float = 0.5  # Minimum leverage (50%)
    max_leverage: float = 2.0  # Maximum leverage (200%)
    volatility_leverage_sensitivity: float = 1.0  # Responsiveness

    # Risk adjustment
    enable_risk_adjustment: bool = True
    risk_free_rate: float = 0.05  # 5% annual
    target_sharpe_ratio: float = 2.0

    # Market regime allocation
    enable_regime_allocation: bool = True
    regime_allocations: Dict[MarketRegime, float] = ...

    # Auto-compounding enhancements
    enable_adaptive_compounding: bool = True
    performance_based_reinvestment: bool = True

    # Real-time optimization
    enable_realtime_optimization: bool = True
    optimization_window_days: int = 30
```

## 📈 Position Sizing Algorithm

The autonomous engine calculates position sizes using a multi-factor approach:

```python
# Step 1: Base position from capital engine
base_position = capital_engine.get_optimal_position_size(balance)

# Step 2: Apply volatility leverage
vol_leverage = (normal_vol / current_vol) ** sensitivity
position = base_position * clamp(vol_leverage, min_lev, max_lev)

# Step 3: Apply regime allocation
regime_multiplier = regime_allocations[current_regime]
position = position * regime_multiplier

# Step 4: Apply risk adjustment (if expected return provided)
sharpe = (expected_return - risk_free_rate) / volatility
risk_factor = sharpe / target_sharpe
position = position * clamp(risk_factor, 0.3, 1.5)

# Step 5: Ensure within bounds
final_position = min(position, available_balance)
```

## 🔧 Build Integration

### Docker Build with Git Metadata

```dockerfile
# Dockerfile includes Git metadata injection
ARG GIT_BRANCH=unknown
ARG GIT_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown

RUN bash inject_git_metadata.sh
```

**Build command:**
```bash
docker build \
  --build-arg GIT_BRANCH=$(git branch --show-current) \
  --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  -t nija-autonomous:latest .
```

### Railway Deployment

```json
{
  "build": {
    "buildCommand": "bash inject_git_metadata.sh && echo 'Metadata injected'"
  },
  "deploy": {
    "startCommand": "bash start.sh"
  }
}
```

### Version Checking

```python
from bot.version_info import get_version_string, get_full_version_info

# Get version string
print(get_version_string())
# Output: NIJA v7.3.0 (Autonomous Scaling Engine) - main@a1b2c3d

# Get full version info
info = get_full_version_info()
print(f"Version: {info['version']}")
print(f"Branch: {info['git_branch']}")
print(f"Commit: {info['git_commit_short']}")
print(f"Built: {info['build_timestamp']}")
```

## 🧪 Testing

### Manual Testing

```python
from bot.autonomous_scaling_engine import get_autonomous_engine, MarketConditions, MarketRegime, VolatilityState

# Create engine
engine = get_autonomous_engine(1000.0)

# Test different market conditions
test_conditions = [
    MarketConditions(15.0, 0.8, MarketRegime.BULL_TRENDING, VolatilityState.LOW, 0.7, 0.9),
    MarketConditions(45.0, -0.6, MarketRegime.BEAR_TRENDING, VolatilityState.HIGH, -0.5, 0.6),
    MarketConditions(25.0, 0.0, MarketRegime.RANGING, VolatilityState.NORMAL, 0.0, 0.8),
]

for conditions in test_conditions:
    engine.update_market_conditions(conditions)
    position = engine.get_optimal_position_size(1000.0)
    print(f"{conditions.regime.value}: ${position:.2f} ({position/1000*100:.1f}%)")
```

### Integration Testing

```bash
# Run autonomous engine tests
python -m pytest bot/test_autonomous_scaling.py -v

# Run with coverage
python -m pytest bot/test_autonomous_scaling.py --cov=bot.autonomous_scaling_engine
```

## 📊 Performance Monitoring

### Key Metrics

The autonomous engine tracks:

1. **Volatility Leverage Efficiency**
   - How well vol-based sizing performs vs static
   - Average leverage applied
   - Win rate by volatility state

2. **Regime Allocation Performance**
   - P/L by market regime
   - Optimal allocation percentages
   - Regime detection accuracy

3. **Risk-Adjusted Returns**
   - Sharpe ratio over time
   - Sortino ratio
   - Maximum drawdown by regime

4. **Optimization Effectiveness**
   - Parameter drift over time
   - Convergence to optimal values
   - Impact on performance

### Status Monitoring

```python
# Get comprehensive status
status = engine.get_autonomous_status()

print(f"Capital: ${status['current_capital']:,.2f}")
print(f"ROI: {status['roi_pct']:.2f}%")
print(f"Current Regime: {status['market_conditions']['regime']}")
print(f"Volatility: {status['market_conditions']['volatility_pct']:.1f}%")

# Check enabled features
features = status['autonomous_features']
for feature, enabled in features.items():
    print(f"{feature}: {'✅' if enabled else '❌'}")
```

## 🚨 Best Practices

### 1. Market Condition Updates
- Update conditions before each trade decision
- Use reliable data sources for volatility/momentum
- Validate regime detection logic with backtests

### 2. Parameter Configuration
- Start conservative (lower max leverage)
- Increase aggressiveness gradually
- Monitor performance before expanding ranges

### 3. Risk Management
- Always enable drawdown protection
- Set appropriate halt thresholds
- Use position limits as final safeguard

### 4. Testing & Validation
- Backtest regime allocations thoroughly
- Validate volatility leverage on historical data
- Test crisis scenarios explicitly

### 5. Monitoring & Alerts
- Track regime changes
- Alert on extreme volatility
- Monitor optimization drift

## 📚 API Reference

### Main Classes

#### AutonomousScalingEngine
```python
class AutonomousScalingEngine:
    def __init__(base_capital, current_capital, base_config, autonomous_config)
    def update_market_conditions(conditions: MarketConditions)
    def get_optimal_position_size(available_balance, expected_return, volatility) -> float
    def record_trade(profit, fees, is_win, new_capital, trade_data)
    def get_autonomous_status() -> Dict
    def get_quick_summary() -> str
```

#### MarketConditions
```python
@dataclass
class MarketConditions:
    volatility_pct: float
    trend_strength: float  # -1.0 to +1.0
    regime: MarketRegime
    volatility_state: VolatilityState
    momentum_score: float  # -1.0 to +1.0
    liquidity_score: float  # 0.0 to 1.0
```

### Enums

```python
class MarketRegime(Enum):
    BULL_TRENDING = "bull_trending"
    BEAR_TRENDING = "bear_trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CRISIS = "crisis"

class VolatilityState(Enum):
    VERY_LOW = "very_low"  # <10%
    LOW = "low"  # 10-20%
    NORMAL = "normal"  # 20-40%
    HIGH = "high"  # 40-60%
    EXTREME = "extreme"  # >60%
```

## 🔮 Future Enhancements

- [ ] Machine learning for regime detection
- [ ] Multi-asset correlation analysis
- [ ] Dynamic stop-loss based on volatility
- [ ] Sentiment integration
- [ ] News event detection
- [ ] Portfolio optimization across exchanges

## 📝 Changelog

### Version 7.3.0 (2026-01-28)
- ✅ Added Git metadata injection at build time
- ✅ Implemented volatility-based leverage
- ✅ Added market regime allocation
- ✅ Implemented risk-adjusted position sizing
- ✅ Added adaptive auto-compounding
- ✅ Implemented real-time parameter optimization

---

**Version**: 7.3.0
**Release Name**: Autonomous Scaling Engine
**Date**: January 28, 2026
**Author**: NIJA Trading Systems
