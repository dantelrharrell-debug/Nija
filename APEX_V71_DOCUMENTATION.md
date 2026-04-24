# NIJA Apex Strategy v7.1 Documentation

## Overview

NIJA Apex Strategy v7.1 is a unified algorithmic trading strategy designed for systematic market entry, risk management, and position management across multiple asset classes.

## Architecture

### Core Modules

1. **nija_apex_strategy_v71.py** - Main strategy class
2. **risk_manager.py** - Dynamic position sizing and risk calculations
3. **execution_engine.py** - Order execution and position tracking
4. **indicators.py** - Technical indicator calculations (VWAP, EMA, RSI, MACD, ADX, ATR)
5. **broker_manager.py** - Multi-broker integration layer

## Features

### 1. Market Filter

The strategy only allows trades when clear trend conditions are met:

**Required Conditions (all must be true):**
- **VWAP Alignment**: Price above VWAP (uptrend) or below (downtrend)
- **EMA Sequence**: EMA9 > EMA21 > EMA50 (uptrend) or reverse (downtrend)
- **MACD Histogram**: Positive (uptrend) or negative (downtrend)
- **ADX > 20**: Sufficient trend strength (no trades if ADX < 20)
- **Volume > 50%**: Current volume must exceed 50% of 5-candle average

**Example:**
```python
allow_trade, direction, reason = strategy.check_market_filter(df, indicators)
# Returns: (True, 'uptrend', 'Uptrend confirmed (ADX=32.5, Vol=120%)')
```

### 2. Entry Logic

#### Long Entry (5 conditions, need 3+ for entry)

1. **Pullback to EMA21 or VWAP** - Price within 0.5% of either level
2. **RSI Bullish Pullback** - RSI 30-70 range, showing recovery (RSI > previous RSI)
3. **Bullish Candlestick** - Bullish engulfing OR hammer pattern
4. **MACD Tick Up** - Histogram increasing (current > previous)
5. **Volume Confirmation** - Current volume >= 60% of last 2 candles average

#### Short Entry (mirror logic with bearish elements)

1. **Pullback to EMA21 or VWAP** - Price within 0.5% of either level
2. **RSI Bearish Pullback** - RSI 30-70 range, showing decline (RSI < previous RSI)
3. **Bearish Candlestick** - Bearish engulfing OR shooting star pattern
4. **MACD Tick Down** - Histogram decreasing (current < previous)
5. **Volume Confirmation** - Current volume >= 60% of last 2 candles average

**Entry occurs at candle close** to confirm the pattern.

**Example:**
```python
signal, score, reason = strategy.check_long_entry(df, indicators)
# Returns: (True, 4, 'Long score: 4/5 (pullback, rsi_pullback, candlestick, volume)')
```

### 3. Dynamic Risk Management

#### Position Sizing (ADX-Based)

Position size adjusts based on trend strength:

| ADX Range | Position Size | Trend Strength |
|-----------|--------------|----------------|
| < 20 | 0% (No trade) | Weak/No trend |
| 20-25 | 2% | Weak trending |
| 25-30 | 4% | Moderate trending |
| 30-40 | 6% | Strong trending |
| 40-50 | 8% | Very strong trending |
| > 50 | 10% | Extremely strong trending |

Signal strength (1-5 score) can further adjust by 80-100% multiplier.

**Example:**
```python
position_size = risk_manager.calculate_position_size(
    account_balance=10000,
    adx=35.0,
    signal_strength=4
)
# Returns: $600 (6% of $10,000 for ADX=35, score=4)
```

#### Stop Loss Calculation

Stop loss = **Swing low/high + ATR(14) * 0.5 buffer**

- **Long**: Stop below swing low (last 10 candles) minus 0.5*ATR
- **Short**: Stop above swing high (last 10 candles) plus 0.5*ATR

This provides:
- Support/resistance based stops
- Volatility-adjusted buffer (wider stops in volatile markets)
- Protection against whipsaws

**Example:**
```python
stop_loss = risk_manager.calculate_stop_loss(
    entry_price=100.00,
    side='long',
    swing_level=98.50,
    atr=1.20
)
# Returns: $97.90 (swing_low $98.50 - 0.5*ATR $0.60)
```

#### Take Profit Levels (R-Multiples)

- **TP1 = 1R** (1x risk): Exit 50%, move stop to breakeven
- **TP2 = 2R** (2x risk): Exit 25% more (75% total out)
- **TP3 = 3R** (3x risk): Exit remaining 25%

**Trailing stop after TP1**: ATR(14) * 1.5 from current price

**Example:**
If entry = $100, stop = $98 (risk = $2):
- TP1 = $102 (1R profit)
- TP2 = $104 (2R profit)
- TP3 = $106 (3R profit)

### 4. Exit Logic

Positions are exited when any of these conditions occur:

1. **Opposite Signal** - Entry conditions for opposite direction detected
2. **Trailing Stop Hit** - Price hits trailing stop (active after TP1)
3. **Trend Break** - EMA9/21 cross against position direction
   - Long exit: EMA9 crosses below EMA21
   - Short exit: EMA9 crosses above EMA21

**Example:**
```python
should_exit, reason = strategy.check_exit_conditions(symbol, df, indicators, current_price)
# Returns: (True, 'Trend break: EMA9 crossed below EMA21')
```

### 5. Smart Filters

Three additional filters prevent bad trades:

1. **News Filter** (stub) - No trades 5 min before/after major news
   - Currently a placeholder for future News API integration
   - Can integrate with Benzinga, Alpha Vantage, etc.

2. **Volume Filter** - No trades if volume < 30% of average

3. **Candle Timing Filter** - No trading during first 6 seconds of new candle
   - Prevents entries on incomplete candles
   - Waits for candle stability

**Example:**
```python
allowed, reason = strategy.check_smart_filters(df, current_time)
# Returns: (False, 'Volume too low (25% of avg)')
```

### 6. AI Momentum Scoring (Skeleton)

Placeholder for future machine learning integration:

```python
momentum_score = strategy.calculate_ai_momentum_score(df, indicators)
# Returns: 0.0-1.0 score (currently simple weighted average)
```

**Future implementation ideas:**
- ML model trained on historical patterns
- Sentiment analysis from news/social media
- Market regime detection (trending vs ranging)
- Volume profile analysis
- Order flow analysis

## Broker Integration

### Supported Brokers

1. **Coinbase Advanced Trade** ✅ Implemented
2. **Alpaca** ✅ Implemented
3. **Binance** ⚠️ Skeleton (ready for implementation)
4. **Interactive Brokers** ⚠️ Skeleton
5. **Custom brokers** via `BaseBroker` interface

### Adding a New Broker

1. Create a class inheriting from `BaseBroker`
2. Implement required methods:
   - `connect()`
   - `get_account_balance()`
   - `place_market_order()`
   - `get_positions()`
   - `get_candles()`
   - `supports_asset_class()`

3. Add to `BrokerManager`

**Example:**
```python
from broker_manager import BaseBroker, BrokerType

class MyBroker(BaseBroker):
    def __init__(self):
        super().__init__(BrokerType.MY_BROKER)

    def connect(self):
        # Implementation
        pass

    # ... implement other methods
```

## Usage Examples

### Basic Usage

```python
from nija_apex_strategy_v71 import NIJAApexStrategyV71
import pandas as pd

# Initialize strategy
strategy = NIJAApexStrategyV71(broker_client=None)

# Load market data
df = get_price_data()  # Your data source

# Analyze market
analysis = strategy.analyze_market(
    df=df,
    symbol='BTC-USD',
    account_balance=10000.0
)

# Check result
if analysis['action'] == 'enter_long':
    print(f"Long entry at ${analysis['entry_price']}")
    print(f"Position size: ${analysis['position_size']}")
    print(f"Stop: ${analysis['stop_loss']}")
```

### With Broker Integration

```python
from broker_manager import CoinbaseBroker
from nija_apex_strategy_v71 import NIJAApexStrategyV71

# Initialize broker
broker = CoinbaseBroker()
broker.connect()

# Initialize strategy with broker
strategy = NIJAApexStrategyV71(broker_client=broker)

# Analyze and execute
analysis = strategy.analyze_market(df, 'BTC-USD', 10000.0)
success = strategy.execute_action(analysis, 'BTC-USD')
```

### Custom Configuration

```python
config = {
    'min_adx': 25,  # Require stronger trends
    'volume_threshold': 0.7,  # 70% volume requirement
    'volume_min_threshold': 0.4,  # 40% minimum
    'candle_exclusion_seconds': 10,  # Wait 10 seconds
    'min_position_pct': 0.03,  # 3% min position
    'max_position_pct': 0.08,  # 8% max position
    'ai_momentum_enabled': True  # Enable AI scoring
}

strategy = NIJAApexStrategyV71(broker_client=broker, config=config)
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_adx` | 20 | Minimum ADX for trade entry |
| `volume_threshold` | 0.5 | Volume must be 50% of 5-candle avg |
| `volume_min_threshold` | 0.3 | Absolute minimum volume (30% avg) |
| `candle_exclusion_seconds` | 6 | Wait time after new candle |
| `news_buffer_minutes` | 5 | Minutes before/after news to avoid |
| `min_position_pct` | 0.02 | Minimum position size (2%) |
| `max_position_pct` | 0.10 | Maximum position size (10%) |
| `ai_momentum_enabled` | False | Enable AI momentum scoring |

## Risk Warnings

1. **No trades if ADX < 20** - Strategy is designed for trending markets only
2. **Position sizing is dynamic** - Smaller positions in weak trends, larger in strong trends
3. **Stop losses are mandatory** - Every trade has a defined stop loss
4. **Partial exits required** - TP1, TP2, TP3 must be honored
5. **Smart filters can block entries** - News, volume, timing filters may prevent trades

## Testing

Run the example script:

```bash
python example_apex_v71.py
```

This demonstrates:
- Strategy initialization
- Market analysis
- Signal detection
- Risk calculations
- Broker integration options

## Integration with Existing NIJA Bot

The v7.1 strategy can be integrated alongside existing NIJA strategies:

```python
# In your main trading loop
from nija_apex_strategy_v71 import NIJAApexStrategyV71

# Initialize
apex_strategy = NIJAApexStrategyV71(broker_client=your_broker)

# In trading loop
for symbol in trading_pairs:
    df = get_candles(symbol)

    # Option 1: Use v7.1 exclusively
    analysis = apex_strategy.analyze_market(df, symbol, balance)
    apex_strategy.execute_action(analysis, symbol)

    # Option 2: Use v7.1 as confirmation
    # Run both old and new strategy, only trade on agreement
```

## Performance Expectations

**Win Rate**: 45-55% (typical for trend-following)
**Risk/Reward**: 1:2 to 1:3 average (via R-multiples)
**Max Drawdown**: Depends on ADX filtering and position sizing
**Best Markets**: Strongly trending markets (ADX > 30)
**Avoid**: Choppy, low-volume, news-driven markets

## Future Enhancements

1. **News API Integration** - Real news event filtering
2. **AI/ML Models** - Advanced momentum scoring
3. **Multi-timeframe Analysis** - Confirm trends across timeframes
4. **Portfolio Risk Management** - Correlation-based position limits
5. **Advanced Order Types** - Limit orders, OCO, bracket orders
6. **Backtesting Framework** - Historical performance testing
7. **Dashboard/Monitoring** - Real-time strategy monitoring

## Support

For questions or issues:
1. Review code comments and docstrings
2. Check example_apex_v71.py for usage patterns
3. Refer to existing NIJA documentation
4. Test with paper trading first

## License

Same as NIJA project (MIT License)

---

**Version**: 7.1
**Last Updated**: December 2025
**Author**: NIJA Trading Systems
