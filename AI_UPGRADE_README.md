# NIJA Trading Bot v8.0 - AI-Enhanced Profitability Upgrade

## 🎯 Overview

NIJA v8.0 introduces major AI and machine learning enhancements designed to maximize daily profitability ($50-$250/day target) through intelligent signal generation, adaptive risk management, and comprehensive trade analysis.

## 🚀 Key Features

### 1. AI/ML Integration (`ai_ml_base.py`)

**Pluggable ML Model Interface**
- Base class for integrating any ML model (sklearn, TensorFlow, PyTorch, etc.)
- Default rule-based model serves as baseline until ML models are trained
- Live data logging for future model training
- Real-time feature extraction from market data

**Features:**
- `MLModelInterface` - Base class for ML models
- `RuleBasedModel` - Default implementation using technical analysis rules
- `LiveDataLogger` - Logs features, signals, and outcomes for ML training
- `EnhancedAIEngine` - Main interface for AI-powered trading

**Usage:**
```python
from ai_ml_base import EnhancedAIEngine, RuleBasedModel

# Initialize with default rule-based model
ai_engine = EnhancedAIEngine(
    model=RuleBasedModel(),
    enable_logging=True  # Log data for future ML training
)

# Generate signal
signal = ai_engine.predict_signal(df, indicators, symbol)
print(f"Signal: {signal['signal']}, Confidence: {signal['confidence']:.2f}")

# Log trade outcome (for future model training)
ai_engine.log_trade_outcome(
    signal_id=signal['signal_id'],
    outcome='win',
    pnl=50.0,
    duration_minutes=45,
    exit_reason='TP1 hit'
)
```

**Future ML Integration (TODO):**
- Train LSTM/Transformer models for price prediction
- Train Random Forest for pattern classification
- Train Gradient Boosting for momentum scoring
- Implement online learning for continuous adaptation
- Create ensemble models combining multiple predictors

### 2. Adaptive Risk Management (`risk_manager.py`)

**Dynamic Position Sizing Based On:**
- Trend strength (ADX) - Base sizing 2-10%
- AI signal confidence - Boost strong signals, reduce weak ones
- Recent win/loss streaks - Reduce after losses, cautiously increase after wins
- Market volatility - Adjust for risk
- Total portfolio exposure - Respect maximum limits

**Features:**
- `AdaptiveRiskManager` - Enhanced risk management with streak tracking
- Winning/losing streak analysis
- Win rate calculation
- Dynamic exposure management
- Detailed sizing breakdowns

**Example:**
```python
from risk_manager import AdaptiveRiskManager

risk_manager = AdaptiveRiskManager(
    min_position_pct=0.02,  # 2% minimum
    max_position_pct=0.10,   # 10% maximum
    max_total_exposure=0.30  # 30% total exposure
)

# Calculate adaptive position size
position_size, breakdown = risk_manager.calculate_position_size(
    account_balance=10000,
    adx=35,                    # Strong trend
    signal_strength=4,         # Strong signal
    ai_confidence=0.75,        # High AI confidence
    volatility_pct=0.012       # Normal volatility
)

print(f"Position Size: ${position_size:.2f}")
print(f"Breakdown: {breakdown}")

# Record trade outcome
risk_manager.record_trade(
    outcome='win',
    pnl=75.0,
    hold_time_minutes=60
)

# Check current streak
streak_type, streak_length = risk_manager.get_current_streak()
print(f"Current Streak: {streak_type} ({streak_length})")
```

### 3. Smart Filters (`smart_filters.py`)

**Time-of-Day Filtering**
- Avoid dead zones (low liquidity periods)
- Target high-activity sessions (US, Europe, Asia)
- Activity multipliers for position sizing

**Volatility Regime Filtering**
- Low volatility: Reduce size (choppy markets)
- Medium volatility: Normal size (ideal conditions)
- High volatility: Reduce size (risky)
- Extreme volatility: Avoid trading

**News Event Filtering (Placeholder)**
- Manual event scheduling
- Buffer zones around major events
- TODO: Integrate news APIs and NLP

**Example:**
```python
from smart_filters import SmartFilterAggregator

filters = SmartFilterAggregator(
    enable_time_filter=True,
    enable_volatility_filter=True,
    enable_news_filter=False
)

# Evaluate all filters
result = filters.evaluate_trade_filters(
    atr_pct=0.012,
    historical_atr=df['close'].pct_change().rolling(20).std(),
    min_time_activity=0.5
)

if result['should_trade']:
    print(f"Filters PASSED - Multiplier: {result['adjustments']['position_size_multiplier']:.2f}x")
    print(f"Reasons: {result['reasons']}")
else:
    print(f"Filters BLOCKED: {result['reasons']}")
```

### 4. Trading Journal (`trade_journal.py`)

**Comprehensive Trade Logging**
- Entry details (price, size, features, AI scores)
- Exit details (price, P&L, duration, reason)
- Performance analytics
- Pattern analysis
- ML training data export

**Features:**
- `TradeJournal` - Main journal class
- Performance metrics calculation
- Winning pattern analysis
- CSV export for analysis
- ML training data preparation

**Example:**
```python
from trade_journal import TradeJournal

journal = TradeJournal(journal_dir='./data/trade_journal')

# Log entry
journal.log_entry(
    trade_id='BTC_20241212_143000',
    symbol='BTC-USD',
    side='long',
    entry_price=42000,
    position_size=1000,
    stop_loss=41500,
    take_profit_levels={'tp1': 42500, 'tp2': 43000, 'tp3': 43500},
    features={'adx': 35, 'rsi': 55, 'atr_pct': 0.012},
    ai_signal={'score': 75, 'confidence': 0.75, 'signal': 'long'},
    market_conditions={'regime': 'trending', 'volatility': 'medium'}
)

# Log exit
journal.log_exit(
    trade_id='BTC_20241212_143000',
    exit_price=42500,
    exit_reason='TP1 hit',
    partial_exit=True,
    exit_pct=0.5
)

# Get performance metrics
metrics = journal.calculate_performance_metrics(days=30)
print(f"Win Rate: {metrics['win_rate']:.1f}%")
print(f"Total P&L: ${metrics['total_pnl']:.2f}")
print(f"Profit Factor: {metrics['profit_factor']:.2f}")

# Print summary
journal.print_summary(days=7)

# Export for ML training
journal.export_for_ml_training()
```

### 5. Enhanced Strategy Pipeline (`nija_apex_strategy_v8.py`)

**Integrated AI-Driven Trading System**
- AI signal generation with confidence scores
- Smart filter evaluation
- Adaptive position sizing
- Comprehensive trade logging
- Performance tracking

**Usage:**
```python
from nija_apex_strategy_v8 import NIJAApexStrategyV8

# Initialize strategy
strategy = NIJAApexStrategyV8(
    broker_client=broker,
    config={
        'enable_ai': True,
        'enable_smart_filters': True,
        'enable_journal': True,
        'min_position_pct': 0.02,
        'max_position_pct': 0.10,
        'max_total_exposure': 0.30,
        'min_ai_confidence': 0.6
    }
)

# Generate entry signal
entry_signal = strategy.generate_entry_signal(df, 'BTC-USD')

if entry_signal:
    # Execute entry
    position = strategy.execute_entry(entry_signal, account_balance=10000)
    
    if position:
        print(f"Entry executed: {position}")

# Check for exits on active positions
for trade_id in list(strategy.active_positions.keys()):
    exit_signal = strategy.check_exit_signal(trade_id, df)
    if exit_signal:
        strategy.execute_exit(trade_id, exit_signal)

# View performance
strategy.print_performance_summary(days=7)
```

## 📊 Configuration Options

### Strategy Configuration

```python
config = {
    # AI Settings
    'enable_ai': True,              # Use AI for signal generation
    'enable_ml_logging': True,      # Log data for future ML training
    'min_ai_confidence': 0.6,       # Minimum AI confidence (0-1)
    
    # Risk Management
    'min_position_pct': 0.02,       # 2% minimum position
    'max_position_pct': 0.10,       # 10% maximum position
    'max_total_exposure': 0.30,     # 30% max total exposure
    
    # Smart Filters
    'enable_smart_filters': True,   # Use time/volatility filters
    'enable_time_filter': True,     # Time-of-day filtering
    'enable_volatility_filter': True, # Volatility regime filtering
    'enable_news_filter': False,    # News event filtering (placeholder)
    'min_time_activity': 0.5,       # Minimum time activity level
    
    # Trading Journal
    'enable_journal': True,         # Log all trades
    'journal_dir': './data/trade_journal',
    
    # Traditional Filters
    'min_adx': 20,                  # Minimum ADX for trend
    'volume_threshold': 0.5,        # Volume as % of average
}
```

## 📈 Performance Optimization

### Daily Profitability Target: $50-$250

The v8.0 upgrade optimizes for profitability through:

1. **Higher Win Rate**
   - AI confidence filtering (only high-quality setups)
   - Smart filters avoid bad conditions
   - Adaptive sizing based on streak performance

2. **Better Risk/Reward**
   - Dynamic position sizing (2-10% based on conviction)
   - AI-enhanced entries at optimal levels
   - Multi-level take profits (TP1/TP2/TP3)

3. **More Efficient Trading**
   - Time-of-day filters target high-activity periods
   - Volatility filters avoid choppy markets
   - Reduced overtrading through smart filters

4. **Continuous Improvement**
   - Trading journal tracks all trades
   - Pattern analysis identifies what works
   - ML logging prepares for future model training

## 🔧 Installation & Setup

### Requirements

No additional dependencies needed beyond existing requirements:
- pandas
- numpy
- Standard Python libraries (datetime, json, os, logging)

### File Structure

```
bot/
├── ai_ml_base.py              # AI/ML infrastructure
├── risk_manager.py            # Adaptive risk management
├── smart_filters.py           # Time/volatility filters
├── trade_journal.py           # Trade logging & analysis
├── nija_apex_strategy_v8.py   # Main strategy (v8.0)
├── indicators.py              # Technical indicators
├── execution_engine.py        # Order execution
└── ...

data/
├── trade_journal/             # Trade logs
│   ├── trades.csv
│   ├── daily_summary.csv
│   ├── performance_metrics.json
│   └── ml_training_data.csv
└── ml_training/               # ML training data
    ├── features_log.csv
    ├── signals_log.csv
    └── outcomes_log.csv
```

### Quick Start

1. **Basic Usage:**
```bash
# The v8.0 strategy can be used as a drop-in replacement for v7.1
python bot/nija_apex_strategy_v8.py
```

2. **Enable All Features:**
```python
from nija_apex_strategy_v8 import NIJAApexStrategyV8

strategy = NIJAApexStrategyV8(
    broker_client=your_broker_client,
    config={
        'enable_ai': True,
        'enable_smart_filters': True,
        'enable_journal': True
    }
)
```

3. **View Performance:**
```python
# Get performance metrics
metrics = strategy.get_performance_summary(days=30)

# Print formatted summary
strategy.print_performance_summary(days=7)
```

## 🔮 Future ML Integration

### Planned ML Models

1. **LSTM/Transformer for Price Prediction**
   - Predict next candle direction and magnitude
   - Multi-timeframe analysis
   - Confidence intervals for predictions

2. **Random Forest for Pattern Classification**
   - Identify high-probability setups
   - Feature importance analysis
   - Ensemble with other models

3. **Gradient Boosting for Momentum Scoring**
   - Real-time momentum assessment
   - Adaptive to changing market conditions
   - Fast inference for live trading

4. **Online Learning**
   - Continuous model updates
   - Adapt to market regime changes
   - No need for periodic retraining

### Training Data Collection

The system is already logging data for future ML training:

```python
# Data is automatically logged in:
# - data/ml_training/features_log.csv    (market features)
# - data/ml_training/signals_log.csv     (trading signals)
# - data/ml_training/outcomes_log.csv    (trade results)

# To prepare training data:
from ai_ml_base import LiveDataLogger

logger = LiveDataLogger()
training_data = logger.get_training_data()

# TODO: Use this data to train ML models
# TODO: Replace RuleBasedModel with trained model
```

## 📝 TODOs & Enhancement Opportunities

### High Priority
- [ ] Train initial ML model on historical data
- [ ] Integrate news API for event filtering
- [ ] Add sentiment analysis for crypto news
- [ ] Implement trailing stop logic with AI
- [ ] Add AI-based exit signals

### Medium Priority
- [ ] Multi-timeframe analysis
- [ ] Portfolio optimization across symbols
- [ ] Correlation-based position limits
- [ ] Advanced pattern recognition
- [ ] Backtesting framework for v8.0

### Low Priority
- [ ] Web dashboard for monitoring
- [ ] Alert system for high-confidence signals
- [ ] Performance visualization
- [ ] Model A/B testing framework
- [ ] Automated hyperparameter tuning

## 🤝 Contributing

This upgrade maintains backward compatibility with v7.1 while adding new features. The old RiskManager is aliased to AdaptiveRiskManager for compatibility.

## 📄 License

Same license as main NIJA project.

## ⚠️ Disclaimer

Trading cryptocurrencies carries risk. Past performance does not guarantee future results. The AI/ML features are designed to improve decision-making but do not eliminate risk. Always use proper risk management and never trade more than you can afford to lose.

---

**Version:** 8.0  
**Date:** December 2024  
**Author:** NIJA Trading Systems
