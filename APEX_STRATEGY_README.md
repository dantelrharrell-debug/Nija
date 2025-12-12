# NIJA Apex Strategy v7.1

## Overview

The NIJA Apex Strategy v7.1 is a sophisticated, high-probability trading strategy designed for professional-grade automated trading. It combines market filters, precise entry triggers, dynamic risk management, and intelligent exit logic to maximize profits while protecting capital.

## Key Features

### 1. **Market Filter**
Only trades when market conditions are favorable:
- **ADX > 20**: Ensures trending market (not choppy/sideways)
- **VWAP Alignment**: Price relative to VWAP confirms trend direction
- **EMA Alignment**: EMA9, EMA21, EMA50 must align with trend
- **MACD Histogram**: Confirms momentum direction
- **Volume Confirmation**: Current volume > 50% of recent average

### 2. **High-Probability Entry Triggers**

#### Long Entry (requires 4 out of 5 conditions):
1. Price pulls back to EMA21 or VWAP (within 0.5%)
2. RSI in bullish zone (40-70)
3. Bullish reversal candle pattern
4. MACD histogram uptick (growing)
5. Volume confirmation (>50% average)

#### Short Entry (mirror of long):
1. Price pulls back to EMA21 or VWAP (within 0.5%)
2. RSI in bearish zone (30-60)
3. Bearish reversal candle pattern
4. MACD histogram downtick (shrinking)
5. Volume confirmation (>50% average)

**Entry Execution**: Only on candle close (no mid-candle entries)

### 3. **Dynamic Position Sizing**
Position size adapts to trend strength (based on ADX):

| Trend Quality | ADX Range | Position Size |
|---------------|-----------|---------------|
| Weak          | 20-25     | 2% of account |
| Good          | 25-30     | 5% of account |
| Strong        | 30-40     | 7% of account |
| Very Strong   | 40+       | 10% of account |

### 4. **Stop Loss System**
- **Method**: Swing low/high + ATR buffer
- **ATR Multiplier**: 1.5x
- **Range**: 0.5% to 2.0% from entry
- **Always Set**: Stop loss placed before entry execution

### 5. **Multi-Stage Take Profit**
Progressive profit-taking with trailing:

| Stage | Profit (R) | Exit % | Action |
|-------|-----------|--------|--------|
| TP1   | 1R        | 33%    | Move stop to break-even |
| TP2   | 2R        | 33%    | Activate trailing stop |
| TP3   | 3R        | 34%    | Final exit or continue trailing |

### 6. **Trailing Stop System**
- **Activation**: After TP1 (1R profit)
- **Method**: ATR(14) × 1.5
- **Behavior**: Only tightens, never widens
- **Updates**: Every candle

### 7. **Exit Logic**
Positions close on:
- Opposite signal detected
- Trailing stop hit
- Trend break (EMA9 crosses EMA21)
- Take profit targets reached

### 8. **Smart Filters**
Trading blocked when:
- **News Events**: 5-minute cooldown after major news (placeholder)
- **Low Volume**: Volume < 30% of average
- **New Candle**: First 5 seconds of candle (prevents false signals)
- **Choppy Market**: ADX < 20

### 9. **AI Momentum Engine (Optional)**
- Enabled only when model/weights available
- Minimum score: 4/10 required for trade
- Features: price momentum, volume profile, trend strength, volatility regime

## Architecture

### Core Modules

```
bot/
├── apex_strategy_v7.py      # Main strategy implementation
├── apex_indicators.py        # Technical indicators (ADX, ATR, MACD, etc.)
├── apex_config.py           # Configuration parameters
├── apex_risk_manager.py     # Position sizing and risk management
├── apex_filters.py          # Smart filters
├── apex_trailing_system.py  # Trailing stop logic
├── apex_ai_engine.py        # Optional AI scoring
└── apex_backtest.py         # Backtesting engine
```

### Broker Support

**Implemented:**
- ✅ Coinbase Advanced Trade (crypto)
- ✅ Alpaca (stocks)

**Placeholders:**
- ⚠️ Binance (crypto/futures) - stub only
- 🔧 Interactive Brokers - use existing adapter
- 🔧 TD Ameritrade - use existing adapter

## Installation

### Requirements

```bash
pip install pandas numpy
pip install coinbase-advanced-py  # For Coinbase
pip install alpaca-py            # For Alpaca (optional)
```

### Environment Variables

For Coinbase (primary):
```bash
export COINBASE_API_KEY="your_api_key"
export COINBASE_API_SECRET="your_api_secret"
export COINBASE_PEM_CONTENT="your_base64_pem"
```

For Alpaca (optional):
```bash
export ALPACA_API_KEY="your_api_key"
export ALPACA_API_SECRET="your_api_secret"
export ALPACA_PAPER="true"  # true for paper trading
```

## Usage

### Basic Example

```python
from apex_strategy_v7 import ApexStrategyV7
import pandas as pd

# Initialize strategy
strategy = ApexStrategyV7(account_balance=10000.0, enable_ai=False)

# Analyze entry opportunity
df = pd.DataFrame(...)  # Your OHLCV data
analysis = strategy.analyze_entry_opportunity(df, symbol="BTC-USD")

if analysis['should_enter']:
    print(f"Entry Signal: {analysis['side']}")
    print(f"Entry Price: ${analysis['entry_price']:.2f}")
    print(f"Stop Loss: ${analysis['stop_loss']:.2f}")
    print(f"Position Size: ${analysis['position_size_usd']:.2f}")
    print(f"Trend Quality: {analysis['trend_quality']}")
```

### Backtesting

```python
from apex_backtest import ApexBacktest
import pandas as pd

# Load historical data
df = pd.read_csv('historical_data.csv')  # OHLCV format

# Initialize backtest
backtest = ApexBacktest(initial_balance=10000.0, enable_ai=False)

# Run backtest
results = backtest.run_backtest(df, symbol="BTC-USD", commission=0.001)

# Print results
backtest.print_results(results)
```

### Live Trading Integration

```python
from apex_strategy_v7 import ApexStrategyV7
from broker_manager import BrokerManager, CoinbaseBroker

# Setup broker
broker_manager = BrokerManager()
coinbase = CoinbaseBroker()
coinbase.connect()
broker_manager.add_broker(coinbase)

# Get balance
balance = broker_manager.get_total_balance()

# Initialize strategy
strategy = ApexStrategyV7(account_balance=balance, enable_ai=False)

# Main trading loop
while True:
    for symbol in ['BTC-USD', 'ETH-USD', 'SOL-USD']:
        # Fetch candles
        candles = coinbase.get_candles(symbol, '5m', 100)
        df = pd.DataFrame(candles)
        
        # Analyze entry
        analysis = strategy.analyze_entry_opportunity(df, symbol)
        
        if analysis['should_enter']:
            # Place order
            broker_manager.place_order(
                symbol,
                analysis['side'],
                analysis['position_size_usd']
            )
    
    time.sleep(300)  # Wait 5 minutes
```

## Configuration

All parameters can be customized in `apex_config.py`:

### Market Filter
```python
MARKET_FILTER = {
    'adx_threshold': 20,
    'volume_threshold': 0.5,
    # ...
}
```

### Position Sizing
```python
POSITION_SIZING = {
    'trend_quality': {
        'weak': {'position_size': 0.02},
        'strong': {'position_size': 0.07},
        # ...
    }
}
```

### Risk Limits
```python
RISK_LIMITS = {
    'max_daily_loss': 0.025,  # 2.5%
    'max_exposure': 0.30,     # 30%
    'max_positions': 5,
    # ...
}
```

## Performance Expectations

### Realistic Targets
- **Win Rate**: 55-65%
- **Average Win**: 1.5-3.0R
- **Average Loss**: 0.5-1.0R
- **Profit Factor**: 1.5-2.5
- **Max Drawdown**: 8-15%

### Risk Factors
- Market volatility
- Slippage on market orders
- Exchange fees (0.1-0.6% per trade)
- API downtime
- Flash crashes

## Backtest vs Live Trading

The strategy is designed to be modular for both:

**Backtest Mode:**
- Uses historical data
- Simulates orders and fills
- Accounts for commission
- Tracks equity curve

**Live Mode:**
- Real broker connections
- Actual order execution
- Real-time data feeds
- Position management

## Safety Features

1. **Risk Limits**: Max exposure, daily loss, position count
2. **Smart Filters**: Block trades in unfavorable conditions
3. **Stop Losses**: Always set before entry
4. **Break-Even**: After TP1, stop moves to entry price
5. **Trailing Stops**: Protect profits as they grow

## Disclaimer

⚠️ **TRADING RISK WARNING**

This strategy involves real financial risk. You can lose your entire account balance. This is not financial advice. Use at your own risk. Always:
- Start with paper trading
- Test thoroughly before live deployment
- Never trade with money you can't afford to lose
- Understand the code before running it
- Monitor positions regularly

## License

MIT License - Free to use and modify

## Support

For issues, questions, or contributions, please refer to the main NIJA repository documentation.

---

**Version**: 7.1  
**Last Updated**: December 2024  
**Status**: Production Ready (Coinbase), Placeholder (Binance)
