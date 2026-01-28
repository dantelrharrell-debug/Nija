# NIJA Multi-Market Intelligence Network (MMIN)

## 🧬 GOD MODE - Global Autonomous Trading Intelligence

**Version:** 1.0.0  
**Status:** Production Ready  
**Date:** January 28, 2026

---

## 🎯 Overview

NIJA MMIN transforms the trading bot from a single-market system into a **global autonomous trading intelligence** that operates across multiple asset classes simultaneously.

### What is MMIN?

MMIN is an advanced multi-market intelligence system that enables:

1. **Cross-Market Learning** - Learn patterns from crypto and apply to equities, forex, and vice versa
2. **Transfer Learning** - Knowledge gained from one asset class enhances trading in others
3. **Macro Regime Forecasting** - Predict economic regimes (risk-on/off, inflation, growth, recession)
4. **Global Capital Routing** - Intelligently allocate capital across markets based on opportunities
5. **Correlation-Aware Intelligence** - Use cross-market correlations for signal confirmation

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      MMIN ENGINE                                 │
│                 (Orchestration Layer)                            │
└─────────────────────────────────────────────────────────────────┘
           │              │              │              │
           ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Multi-Market │ │ Correlation  │ │ Macro Regime │ │   Transfer   │
│     Data     │ │   Analyzer   │ │  Forecaster  │ │   Learning   │
│  Collector   │ │              │ │              │ │    Engine    │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
           │              │              │              │
           └──────────────┴──────────────┴──────────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  Global Capital      │
                   │     Router           │
                   └──────────────────────┘
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │    CRYPTO │ FOREX │ EQUITIES │ BONDS      │
        │  (Coinbase, Kraken, Binance, Alpaca, etc) │
        └───────────────────────────────────────────┘
```

---

## 📦 Core Components

### 1. Multi-Market Data Collector

**Location:** `bot/mmin/data_collector.py`

Collects and normalizes data from multiple asset classes:
- **Crypto:** BTC, ETH, SOL, AVAX, MATIC, etc.
- **Forex:** EUR/USD, GBP/USD, USD/JPY, etc.
- **Equities:** SPY, QQQ, AAPL, MSFT, NVDA, etc.
- **Commodities:** GLD, SLV, USO, DBA
- **Bonds:** TLT, IEF, SHY

**Features:**
- Unified OHLCV data format across all markets
- Real-time and historical data collection
- Data synchronization across markets
- Quality metrics and monitoring

### 2. Cross-Market Correlation Analyzer

**Location:** `bot/mmin/correlation_analyzer.py`

Analyzes correlations between different asset classes:

**Features:**
- Rolling correlation matrices (20, 50, 100, 200 periods)
- Lead-lag relationship detection
- Correlation regime detection (increasing/decreasing/stable)
- Market clustering
- Diversification scoring

**Use Cases:**
- Find leading indicators across markets
- Identify diversification opportunities
- Confirm signals with correlated assets
- Detect correlation breakdowns (risk events)

### 3. Macro Regime Forecaster

**Location:** `bot/mmin/macro_regime_forecaster.py`

Forecasts global macro economic regimes:

**Regimes Detected:**
- **Risk On:** Crypto ↑, Equities ↑, Bonds ↓, VIX ↓
- **Risk Off:** Crypto ↓, Equities ↓, Bonds ↑, VIX ↑
- **Inflation:** Commodities ↑, Bonds ↓
- **Deflation:** Commodities ↓, Bonds ↑
- **Growth:** Equities ↑, Crypto ↑
- **Recession:** Everything ↓ except bonds/USD

**Trading Implications:**
Each regime comes with specific trading recommendations:
- Preferred markets
- Position sizing (aggressive/balanced/conservative)
- Strategy focus (momentum/defensive/preservation)
- Leverage guidance

### 4. Transfer Learning Engine

**Location:** `bot/mmin/transfer_learning.py`

Enables pattern transfer across different asset classes:

**Features:**
- Extract normalized features from any market
- Learn patterns from successful trades
- Find similar patterns across markets
- Transfer patterns between asset classes
- Track transfer performance

**Example:**
```
Crypto breakout pattern (90% success) 
    → Transfer to equity market 
    → Applied with 75% adjusted confidence
```

### 5. Global Capital Router

**Location:** `bot/mmin/global_capital_router.py`

Intelligently routes capital across markets:

**Allocation Strategies:**
1. **Fixed:** Pre-defined percentages per market
2. **Balanced:** Equal allocation across all markets
3. **Adaptive:** Dynamic based on performance + regime + correlations
4. **Aggressive:** Concentrate in top 3 performers

**Allocation Factors:**
- Sharpe ratio (30%)
- Win rate (20%)
- Profit factor (20%)
- Opportunity count (15%)
- Correlation diversity (15%)

### 6. MMIN Engine (Main Orchestrator)

**Location:** `bot/mmin/mmin_engine.py`

Main intelligence engine that coordinates all components:

**Analysis Loop:**
1. Collect multi-market data
2. Calculate cross-market correlations
3. Forecast macro regime
4. Discover and transfer patterns
5. Calculate optimal capital allocation
6. Generate signals with cross-market confirmation
7. Execute trades across markets

---

## 🚀 Quick Start

### Installation

MMIN is already integrated into NIJA. No additional dependencies required.

### Basic Usage

```python
from bot.mmin import MMINEngine

# Initialize MMIN
engine = MMINEngine()

# Run market analysis
analysis = engine.analyze_markets(
    timeframe='1h',
    limit=500
)

# Results
print(f"Macro Regime: {analysis['macro_regime']['regime'].value}")
print(f"Signals: {len(analysis['signals'])}")
print(f"Capital Allocation: {analysis['capital_allocation']}")

# Get status
status = engine.get_status()
print(f"Intelligence Level: {status['intelligence_level']}")
```

### Testing

Run the comprehensive test suite:

```bash
python test_mmin.py
```

This tests all MMIN components and validates the full system.

---

## 🎮 Configuration

MMIN configuration is in `bot/mmin/mmin_config.py`

### Key Settings

```python
# Enable/disable MMIN
MMIN_ENGINE_CONFIG = {
    'enabled': True,
    'mode': 'adaptive',  # 'conservative', 'balanced', 'adaptive', 'aggressive'
    'intelligence_level': 'god_mode',  # 'basic', 'advanced', 'god_mode'
    'cross_market_signals_required': 2,  # Require N market confirmations
}

# Markets to monitor
MARKET_CATEGORIES = {
    'crypto': ['BTC-USD', 'ETH-USD', 'SOL-USD', ...],
    'equities': ['SPY', 'QQQ', 'AAPL', ...],
    'forex': ['EUR/USD', 'GBP/USD', ...],
    'commodities': ['GLD', 'SLV', ...],
    'bonds': ['TLT', 'IEF', ...],
}

# Capital allocation strategy
CAPITAL_ALLOCATION_CONFIG = {
    'allocation_strategy': 'adaptive',  # Recommended
    'min_allocation_per_market': 0.05,  # 5% minimum
    'max_allocation_per_market': 0.50,  # 50% maximum
}
```

---

## 📊 Use Cases

### 1. Cross-Market Signal Confirmation

MMIN requires signals to be confirmed across multiple markets:

```
Example:
- BTC-USD shows bullish setup (crypto)
- Correlation analyzer finds BTC ↔ NASDAQ (0.85 correlation)
- NASDAQ also shows bullish momentum
- Signal confidence increased due to cross-market confirmation
```

### 2. Macro Regime-Based Trading

Adapt strategy based on global economic regime:

```
Scenario: MMIN detects "Risk Off" regime
- Bonds rising, equities falling, crypto falling
- Action: Reduce crypto/equity exposure
- Action: Increase bond/USD allocation
- Action: Tighten stop losses
- Action: Focus on defensive strategies
```

### 3. Transfer Learning Example

Learn from one market, apply to another:

```
Pattern learned from crypto:
- RSI oversold + volume surge + breakout = 85% win rate

Pattern transferred to equities:
- Same setup recognized in SPY
- Adjusted confidence: 72% (accounting for transfer risk)
- Trade executed with smaller position size
```

### 4. Intelligent Capital Allocation

Dynamic allocation based on opportunity + regime:

```
Current State:
- Macro regime: Growth
- Crypto: 8 opportunities, Sharpe 2.1
- Equities: 12 opportunities, Sharpe 1.8
- Forex: 3 opportunities, Sharpe 1.2

Allocation:
- Crypto: 45% (high performance + growth regime)
- Equities: 40% (many opportunities + growth regime)
- Forex: 15% (fewer opportunities)
```

---

## 📈 Performance Metrics

MMIN tracks comprehensive performance metrics:

```python
status = engine.get_status()

{
    'performance': {
        'total_signals': 247,
        'successful_signals': 156,
        'cross_market_confirmations': 189,
        'regime_changes': 12,
    },
    'data_quality': {
        'cached_symbols': 45,
        'missing_data_count': 3,
        'total_updates': 1024,
    },
    'learning_stats': {
        'total_patterns': 89,
        'transfer_routes': 6,
        'transfer_performance': {...},
    }
}
```

---

## 🔒 Security Considerations

- All API keys remain in `.env` (never committed)
- MMIN uses existing broker integrations (no new API access)
- Data collected is OHLCV only (public data)
- No personal information collected
- Transfer learning is local (no external ML services)

---

## 🎯 Intelligence Levels

### Basic Mode
- Single-market analysis
- Simple correlations
- Fixed allocation

### Advanced Mode
- Multi-market monitoring
- Correlation-based signals
- Regime detection
- Adaptive allocation

### GOD Mode (Current)
- Full cross-market learning
- Transfer learning
- Macro forecasting
- Global capital routing
- Correlation-aware portfolio intelligence

---

## 🔮 Future Enhancements

### Phase 2 (Optional)
- [ ] Reinforcement learning for allocation
- [ ] Sentiment analysis across markets
- [ ] Options and derivatives integration
- [ ] AI-powered regime prediction (LSTM/Transformer)
- [ ] Multi-timeframe analysis
- [ ] Alternative data integration (on-chain, satellite, etc.)

---

## 📚 API Reference

### MMINEngine

```python
class MMINEngine:
    def __init__(self, broker_manager=None, config=None)
    def analyze_markets(self, timeframe='1h', limit=500) -> Dict
    def get_status() -> Dict
    def enable()
    def disable()
```

### MultiMarketDataCollector

```python
class MultiMarketDataCollector:
    def collect_market_data(market_type, symbols, timeframe, limit) -> Dict
    def collect_all_markets(timeframe, limit) -> Dict
    def get_synchronized_data(symbols_map, limit) -> pd.DataFrame
    def get_quality_metrics() -> Dict
```

### CrossMarketCorrelationAnalyzer

```python
class CrossMarketCorrelationAnalyzer:
    def calculate_correlations(data) -> Dict
    def find_correlated_pairs(corr_matrix, threshold) -> List
    def detect_lead_lag(data, sym1, sym2, max_lag) -> Dict
    def get_diversification_score(portfolio, corr_matrix) -> float
```

### MacroRegimeForecaster

```python
class MacroRegimeForecaster:
    def forecast_regime(market_data) -> Dict
    def get_regime_transitions(lookback) -> List
```

### TransferLearningEngine

```python
class TransferLearningEngine:
    def extract_features(df, market_type) -> np.ndarray
    def learn_pattern(data, market_type, pattern_type, outcome) -> Pattern
    def find_similar_patterns(data, market_type, pattern_types, min_confidence) -> List
    def transfer_pattern(pattern, target_market) -> Dict
```

### GlobalCapitalRouter

```python
class GlobalCapitalRouter:
    def calculate_allocation(market_metrics, correlations, macro_regime, total_capital) -> Dict
    def score_opportunity(opportunity) -> float
    def suggest_rebalance(current, target, threshold) -> Dict
```

---

## 🐛 Troubleshooting

### Issue: No data collected
**Solution:** Check broker connections and API credentials

### Issue: Low signal count
**Solution:** Adjust `min_score_threshold` in configuration

### Issue: Too many signals
**Solution:** Increase `cross_market_signals_required` for stricter filtering

---

## 📞 Support

For questions or issues:
1. Check this documentation
2. Review test suite (`test_mmin.py`)
3. Check logs for detailed error messages
4. Review configuration in `mmin_config.py`

---

## 🏆 Summary

NIJA MMIN represents the **next evolution** of autonomous trading:

✅ **Cross-Market Learning** - Patterns transfer across asset classes  
✅ **Transfer Learning** - Knowledge compounds across markets  
✅ **Macro Forecasting** - Global regime awareness  
✅ **Global Capital Routing** - Intelligent allocation  
✅ **Correlation Intelligence** - Multi-market confirmation  

**NIJA is now a GLOBAL AUTONOMOUS TRADING INTELLIGENCE**

---

*"The future of trading is not single-market bots. It's global intelligence that learns, adapts, and operates across all markets simultaneously."*

---

**Version:** 1.0.0  
**Author:** NIJA Trading Systems  
**Date:** January 28, 2026
