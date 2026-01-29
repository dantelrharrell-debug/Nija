# Elite Profit Engine v2 - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Prerequisites
- NIJA trading bot already set up
- Python 3.8+ installed
- Active Coinbase/Kraken accounts

---

## Step 1: Choose Your Profile (30 seconds)

Pick based on your risk tolerance:

```python
# CONSERVATIVE - Safest, steady growth
# Best for: New users, small accounts ($500-$2000)
profile = 'conservative'

# MODERATE - Balanced (RECOMMENDED)
# Best for: Most users, medium accounts ($2000-$10000)
profile = 'moderate'

# AGGRESSIVE - Highest returns, higher risk
# Best for: Experienced traders, larger accounts ($10000+)
profile = 'aggressive'

# ELITE - Maximum optimization
# Best for: Advanced users who monitor closely
profile = 'elite'
```

---

## Step 2: Initialize the Engine (1 minute)

Add to your main trading strategy file:

```python
from bot.elite_profit_engine_v2 import get_elite_profit_engine_v2
from bot.elite_profit_engine_config import get_config_profile
from bot.smart_capital_rotator import StrategyType

# Get configuration
config = get_config_profile('moderate')  # or your chosen profile

# Initialize Elite Engine
elite_engine = get_elite_profit_engine_v2(
    base_capital=10000.0,  # Your starting capital
    config=config
)

print("🏆 Elite Profit Engine v2 initialized!")
```

---

## Step 3: Integrate with Your Strategy (2 minutes)

### Calculate Optimal Position Size

```python
# When generating a trade signal
position_result = elite_engine.calculate_optimal_position_size(
    df=price_dataframe,        # Your OHLCV data
    indicators=indicators,      # Your technical indicators (must include 'atr', 'adx')
    signal_score=85.0,          # Your signal quality score (0-100)
    strategy_type=StrategyType.MOMENTUM  # SCALP, MOMENTUM, or TREND
)

# Use the optimal position size
position_size = position_result['final_position_usd']
print(f"Optimal position: ${position_size:.2f}")
```

### Check if Trade Should Be Taken

```python
from bot.trade_frequency_optimizer import SignalQuality

should_take, reason = elite_engine.should_take_trade(
    signal_score=85.0,
    min_quality=SignalQuality.FAIR  # Minimum quality threshold
)

if should_take:
    # Execute trade with optimal position size
    execute_trade(position_size)
else:
    print(f"Trade rejected: {reason}")
```

### Record Trade Results

```python
# After trade closes
elite_engine.record_trade_result(
    strategy_type=StrategyType.MOMENTUM,  # Which strategy was used
    gross_profit=150.0,                    # Profit before fees
    fees=5.0,                              # Trading fees paid
    is_win=True                            # True if profitable
)
```

---

## Step 4: Monitor Performance (ongoing)

### Get Quick Status

```python
status = elite_engine.get_current_status()
print(f"Balance: ${status['current_balance']:,.2f}")
print(f"Daily Profit: ${status['daily_profit']:,.2f}")
print(f"Locked Profit: ${status['locked_profit']:,.2f}")
print(f"Trading Mode: {status['trading_mode']}")
```

### Get Detailed Report

```python
# Get comprehensive report from all subsystems
report = elite_engine.get_master_report(df, indicators)
print(report)
```

---

## Complete Integration Example

Here's a complete example integrating Elite Profit Engine v2 with NIJA:

```python
from bot.elite_profit_engine_v2 import get_elite_profit_engine_v2
from bot.elite_profit_engine_config import get_config_profile
from bot.smart_capital_rotator import StrategyType
from bot.trade_frequency_optimizer import SignalQuality

class NIJAEliteStrategy:
    def __init__(self, broker):
        self.broker = broker
        
        # Initialize Elite Profit Engine v2
        config = get_config_profile('moderate')
        self.elite_engine = get_elite_profit_engine_v2(
            base_capital=broker.get_balance(),
            config=config
        )
    
    def scan_and_trade(self):
        """Main trading loop"""
        
        # Get market data
        df = self.broker.get_candles('BTC-USD', '5m', 100)
        indicators = self.calculate_indicators(df)
        
        # Generate signal
        signal_score = self.calculate_signal_score(df, indicators)
        
        # Check if should take trade
        should_take, reason = self.elite_engine.should_take_trade(
            signal_score=signal_score,
            min_quality=SignalQuality.FAIR
        )
        
        if not should_take:
            print(f"No trade: {reason}")
            return
        
        # Calculate optimal position size
        position = self.elite_engine.calculate_optimal_position_size(
            df=df,
            indicators=indicators,
            signal_score=signal_score,
            strategy_type=StrategyType.MOMENTUM
        )
        
        # Execute trade
        order = self.broker.buy(
            symbol='BTC-USD',
            size_usd=position['final_position_usd']
        )
        
        print(f"✅ Trade executed: ${position['final_position_usd']:.2f}")
        
        # Monitor and close when signal exits
        # ... (your exit logic)
        
        # After trade closes, record result
        self.elite_engine.record_trade_result(
            strategy_type=StrategyType.MOMENTUM,
            gross_profit=150.0,  # Your actual profit
            fees=5.0,            # Your actual fees
            is_win=True          # True if profitable
        )
    
    def calculate_indicators(self, df):
        """Calculate required indicators"""
        from bot.indicators import calculate_atr, calculate_rsi, calculate_macd
        
        return {
            'atr': calculate_atr(df, period=14),
            'rsi': calculate_rsi(df, period=14),
            'adx': self.calculate_adx(df),  # Your ADX calculation
            # ... other indicators
        }
    
    def calculate_signal_score(self, df, indicators):
        """Calculate signal quality (0-100)"""
        # Your signal scoring logic
        # Should return a score from 0-100
        return 75.0  # Example

# Usage
broker = YourBroker()  # Your broker instance
strategy = NIJAEliteStrategy(broker)
strategy.scan_and_trade()
```

---

## Configuration Tweaks

### Adjust Position Sizing

```python
config = get_config_profile('moderate')

# Make positions larger/smaller
config['volatility_sizer']['base_position_pct'] = 0.07  # 7% instead of 5%

# Change position range
config['volatility_sizer']['min_position_pct'] = 0.03   # 3% min
config['volatility_sizer']['max_position_pct'] = 0.12   # 12% max
```

### Adjust Leverage

```python
config['leverage']['leverage_mode'] = 'conservative'  # 1x-2x
# or
config['leverage']['leverage_mode'] = 'aggressive'    # 1x-5x

# Set hard cap
config['leverage']['absolute_max_leverage'] = 3.0     # Never exceed 3x
```

### Adjust Daily Profit Target

```python
config['profit_locking']['daily_target_pct'] = 0.025  # 2.5% daily target
```

### Disable Features

```python
# Disable leverage (always 1x)
config['leverage']['leverage_mode'] = 'disabled'

# Change compounding
config['compounding_strategy'] = 'conservative'  # More preservation
```

---

## Monitoring Tips

### Daily Checklist
1. Check daily profit progress
2. Review locked profit amount
3. Check trading mode (Normal/Conservative/Protective)
4. Review capital rotation between strategies
5. Check current leverage level

### Weekly Review
1. Run master report
2. Analyze which strategy performs best
3. Check win rate and CAGR
4. Adjust profile if needed

### Red Flags 🚩
- Win rate drops below 45% → System will reduce leverage automatically
- Drawdown exceeds 15% → Check your signal quality
- Daily profit frequently negative → Review your strategy logic
- Locked profit = 0 → Not hitting profit targets

---

## FAQ

**Q: How often should I check it?**  
A: Daily for profit status, weekly for detailed review. System runs autonomously.

**Q: Can I use this with paper trading?**  
A: Yes! Set leverage_mode to 'disabled' for paper trading.

**Q: What if I want to disable a feature?**  
A: Edit the config before initializing. See "Configuration Tweaks" above.

**Q: How do I know if it's working?**  
A: Check locked_profit > 0 and trading_mode changes as you hit targets.

**Q: Can I run multiple instances?**  
A: Yes, create separate instances with different configs/capitals.

---

## Troubleshooting

### "Module not found" errors
```bash
pip install pandas numpy
```

### "Invalid frequency" errors
Use lowercase 'h' instead of 'H' for pandas date_range:
```python
pd.date_range('2024-01-01', periods=100, freq='1h')  # Correct
```

### Import path issues
Use relative imports when running from bot/ directory:
```python
from elite_profit_engine_v2 import get_elite_profit_engine_v2
```

### Data persistence issues
Check that `data/` directory exists and is writable.

---

## Next Steps

1. **Start with Conservative** - Test for 1-2 weeks
2. **Review Performance** - Check master report weekly
3. **Upgrade to Moderate** - After proving success
4. **Fine-tune** - Adjust based on your results
5. **Scale Up** - Increase capital as you gain confidence

---

## Need Help?

- 📖 Full documentation: `ELITE_PROFIT_ENGINE_V2_DOCUMENTATION.md`
- 🔧 Configuration details: `bot/elite_profit_engine_config.py`
- 💻 Example code: `bot/elite_profit_engine_v2.py` (bottom of file)

---

**Remember:** Elite Profit Engine v2 is a force multiplier. Your signal quality still matters most. Feed it good signals, and it will optimize everything else! 🚀
