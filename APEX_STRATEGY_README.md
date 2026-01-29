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
## 🚀 Production-Ready Trading System

NIJA Apex Strategy v7.1 is a unified, production-ready trading system designed for high-probability, multi-confirmation trade execution with aggressive capital protection.

---

## ✨ Key Features

### 1. **Strict Market-State Filtering**
Only trades in clean, strong trends with favorable conditions:
- **VWAP Alignment**: Price must be above/below VWAP for long/short
- **EMA Alignment**: EMA9 > EMA21 > EMA50 (bullish) or reverse (bearish)
- **MACD Histogram**: Confirms momentum direction
- **ADX > 20**: Ensures strong trend, avoids choppy markets
- **Minimum Volume**: 1.5x average volume for valid signals

### 2. **Multi-Confirmation Entry Logic**
Requires 4 out of 6 confirmations for trade entry:
1. ✅ VWAP alignment (price position)
2. ✅ EMA alignment (trend structure)
3. ✅ RSI favorable (30-70 range, not extreme)
4. ✅ MACD histogram increasing/decreasing
5. ✅ Volume confirmation (>1.5x average)
6. ✅ Momentum candle OR pullback setup (VWAP/EMA21)

### 3. **Dynamic ADX-Weighted Position Sizing**
Position size adapts to trend strength:
- **Weak trend (ADX < 20)**: 0.5x base size
- **Moderate trend (ADX 20-40)**: 0.5x to 1.0x base size
- **Strong trend (ADX > 40)**: 1.0x to 1.5x base size

Signal quality also affects size:
- **Score 6/6**: 1.2x multiplier
- **Score 5/6**: 1.0x multiplier
- **Score 4/6**: 0.8x multiplier

### 4. **ATR-Based Stop-Loss with Buffer**
- Stop-loss = Entry ± (ATR × 1.5)
- Minimum 0.3% stop-loss
- Accounts for volatility to avoid premature stops

### 5. **Tiered Take-Profit System**
- **TP1 (+0.8%)**: Exit 50%, activate trailing stop
- **TP2 (+1.5%)**: Exit 30% (80% total out)
- **TP3 (+2.5%)**: Exit final 20%, let runner trail

### 6. **Trailing Stop Post-TP1**
- Activates after TP1 hit
- Initial trail: 0.5% below highest price (long)
- Tightens to 0.3% after TP2
- Locks in profits while letting winners run

### 7. **Aggressive Capital Protection**
- **Max daily loss**: 2.5% of account
- **Max drawdown**: 10% of account (stops trading)
- **Max total exposure**: 30% across all positions
- **Chop detection**: No trades when ADX < 20

### 8. **Smart Filters**
- **News cooldown**: No trades for 3 minutes after major news
- **Candle timing**: Avoids first 5 seconds of new candle
- **Low volume filter**: Requires minimum volume threshold
- **Spread check**: Avoids wide spreads (>0.1%)

### 9. **Extensible Architecture**
- **Multi-broker support**: Coinbase, Binance, Alpaca (skeletons ready)
- **AI momentum scoring**: Framework for ML integration
- **Market regime detection**: Adapts to trending/ranging/volatile markets
- **Adaptive signal weighting**: Adjusts signal importance by regime

---

## 📁 Module Structure

```
bot/
├── nija_apex_strategy.py      # Core strategy class
├── indicators_apex.py          # Enhanced indicators (ADX, ATR, MACD, momentum)
├── risk_management.py          # Position sizing, stops, take-profits
├── market_filters.py           # Chop detection, volume, news, timing filters
├── broker_integration.py       # Multi-broker adapter framework
├── ai_momentum.py              # AI momentum scoring (skeleton)
└── apex_config.py              # Configuration (no secrets!)
```

---

## 🔧 Configuration

All parameters are centralized in `apex_config.py`:

### Market Filtering
```python
MARKET_FILTERING = {
    'min_adx': 20,              # Minimum trend strength
    'min_volume_multiplier': 1.5,  # Min volume vs average
}
```

### Entry Requirements
```python
ENTRY_CONFIG = {
    'min_signal_score': 4,      # Min confirmations (out of 6)
    'require_ema_alignment': True,
    'require_vwap_alignment': True,
}
```

### Risk Management
```python
RISK_CONFIG = {
    'max_risk_per_trade': 0.02,  # 2% per trade
    'max_daily_loss': 0.025,     # 2.5% daily limit
    'max_total_exposure': 0.30,  # 30% max exposure
    'max_drawdown': 0.10,        # 10% max drawdown
}
```

### Position Sizing
```python
POSITION_SIZING = {
    'base_position_size': 0.03,  # 3% base
    'min_position_size': 0.01,   # 1% minimum
    'max_position_size': 0.10,   # 10% maximum
    'use_adx_weighting': True,
}
```

### Stop-Loss & Take-Profit
```python
STOP_LOSS_CONFIG = {
    'atr_stop_multiplier': 1.5,
    'min_stop_pct': 0.003,
}

TAKE_PROFIT_CONFIG = {
    'tp1': {'pct': 0.008, 'exit_size': 0.50},
    'tp2': {'pct': 0.015, 'exit_size': 0.30},
    'tp3': {'pct': 0.025, 'exit_size': 0.20},
}
```

---

## 🚦 Usage Example

```python
from nija_apex_strategy import NijaApexStrategyV71
import pandas as pd

# Initialize strategy with account balance
strategy = NijaApexStrategyV71(account_balance=10000.0)

# Get market data (OHLCV DataFrame)
df = get_market_data('BTC-USD', timeframe='5m', limit=100)

# Check if we should enter a trade
should_enter, trade_plan = strategy.should_enter_trade(df)

if should_enter:
    print(f"✅ TRADE SIGNAL: {trade_plan['signal'].upper()}")
    print(f"   Score: {trade_plan['score']}/6")
    print(f"   Entry: ${trade_plan['entry_price']:.2f}")
    print(f"   Size: ${trade_plan['position_size_usd']:.2f} ({trade_plan['position_size_pct']*100:.1f}%)")
    print(f"   Stop: ${trade_plan['stop_loss']:.2f}")
    print(f"   TP1: ${trade_plan['take_profits']['tp1']['price']:.2f}")
    print(f"   TP2: ${trade_plan['take_profits']['tp2']['price']:.2f}")
    print(f"   TP3: ${trade_plan['take_profits']['tp3']['price']:.2f}")
else:
    print("❌ No trade signal")
```

---

## 🔐 Security Best Practices

### ✅ DO:
- Load API keys from environment variables
- Use `.env` file for local development (never commit to git)
- Store secrets in secure vaults (Railway, AWS Secrets Manager, etc.)
- Enable IP whitelisting on broker APIs
- Set API permissions to trade-only (no withdrawals)

### ❌ DON'T:
- Hardcode API keys in source code
- Commit `.env` files to version control
- Share API secrets in logs or error messages
- Use production keys in testing/development

### Environment Variables Required:
```bash
COINBASE_API_KEY=your_api_key
COINBASE_API_SECRET=your_api_secret
COINBASE_PEM_CONTENT=your_base64_encoded_pem
LIVE_MODE=true  # Set to "false" for paper trading

# Optional for other brokers
BINANCE_API_KEY=your_binance_key
BINANCE_API_SECRET=your_binance_secret
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret
```

---

## 🎯 Multi-Broker Support

The strategy supports multiple brokers through a unified interface:

### Coinbase (Implemented)
```python
from broker_integration import BrokerFactory

broker = BrokerFactory.create_broker('coinbase')
broker.connect()
balance = broker.get_account_balance()
```

### Binance (Skeleton)
```python
broker = BrokerFactory.create_broker('binance', testnet=True)
# TODO: Implement full Binance integration
```

### Alpaca (Skeleton)
```python
broker = BrokerFactory.create_broker('alpaca', paper=True)
# TODO: Implement full Alpaca integration
```

---

## 🤖 AI Momentum Scoring (Future)

Framework in place for ML integration:

```python
from ai_momentum import MomentumScorer, AIRegimedDetector

# Market regime detection
regime_detector = AIRegimedDetector()
regime = regime_detector.detect_regime(df, adx, atr_pct)

# Momentum scoring (currently rule-based)
scorer = MomentumScorer(use_ml=False)
score = scorer.calculate_momentum_score(indicators, market_data)
```

**Future capabilities:**
- LSTM/Transformer models for price prediction
- Random Forest for pattern classification
- Gradient Boosting for momentum scoring
- Online learning for continuous adaptation

---

## 📊 Performance Expectations

### Realistic Targets
- **Win Rate**: 55-65%
- **Average Win**: +1.5% to +3.0%
- **Average Loss**: -0.5% to -1.0% (protected by ATR stops)
- **Daily Target**: +1% to +2%
- **Max Drawdown**: -5% to -8%

### Risk Factors
- **Crypto Volatility**: 24/7 markets can gap unexpectedly
- **Exchange Fees**: ~0.5-0.6% per trade on Coinbase
- **Slippage**: Market orders may have price impact
- **API Downtime**: Exchange outages can prevent exits
- **Flash Crashes**: Stops may not fill at expected prices

---

## 🛠️ Development Roadmap

### Completed ✅
- [x] Core strategy class with multi-confirmation logic
- [x] Enhanced indicators (ADX, ATR, MACD, momentum)
- [x] Risk management with ADX weighting
- [x] Tiered take-profits and trailing stops
- [x] Market filters (chop, volume, timing, news)
- [x] Multi-broker interface framework
- [x] Configuration management (no secrets)

### In Progress 🚧
- [ ] Coinbase broker adapter implementation
- [ ] Backtesting framework integration
- [ ] Live trading execution loop
- [ ] Position management and monitoring

### Future 🔮
- [ ] Binance adapter implementation
- [ ] Alpaca adapter implementation
- [ ] ML-based momentum scoring
- [ ] Sentiment analysis integration
- [ ] Multi-timeframe analysis
- [ ] Advanced order types (OCO, bracket orders)

---

## 📝 License

MIT License - Use freely, no warranty provided.

---

## ⚠️ Disclaimer

**LIVE TRADING RISK**: This bot executes REAL trades with REAL money. You can lose your entire account balance.

- **Not Financial Advice**: This is a tool. You are solely responsible for all trading decisions.
- **No Guarantees**: Past performance does not guarantee future results.
- **Total Loss Possible**: Never trade with money you cannot afford to lose completely.

**USE AT YOUR OWN RISK**

---

## 🏆 NIJA Apex Philosophy

> **"Discipline, precision, and protection generate consistent profits."**

Core principles:
1. **Quality over Quantity**: 4/6 confirmations ensure high-probability setups
2. **Risk-First Approach**: Every trade has defined stop-loss and take-profit
3. **Let Winners Run**: Trailing system captures extended moves
4. **Cut Losers Fast**: ATR-based stops prevent small losses from becoming large
5. **Adapt to Conditions**: Chop detection, regime adaptation, drawdown protection
6. **Systematic Execution**: No emotions, no FOMO, no revenge trading

---

**Version**: 7.1
**Last Updated**: December 2024
**Status**: Production Ready (Coinbase), Placeholder (Binance)
**Last Updated**: December 12, 2025
**Status**: Production-Ready Architecture
