# NIJA Apex Strategy v7.1

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
**Last Updated**: December 12, 2025  
**Status**: Production-Ready Architecture
