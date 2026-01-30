# NAMIE Quick Start Guide 🚀

Get NAMIE running in 5 minutes.

## Step 1: Install (Already Done)

NAMIE is now part of NIJA. No additional installation needed.

## Step 2: Basic Integration

### Simplest Possible Integration (1 line)

```python
from bot.namie_integration import quick_namie_check

# In your trading loop
should_trade, reason, signal = quick_namie_check(df, indicators, "BTC-USD")

if should_trade:
    # Execute your trade
    # Use signal.position_size_multiplier to adjust size
    adjusted_size = base_size * signal.position_size_multiplier
    execute_trade(adjusted_size)
```

### Standard Integration (Recommended)

```python
from bot.namie_integration import NAMIEIntegration

# Initialize once
namie = NAMIEIntegration()

# In your trading loop
for symbol in trading_pairs:
    # Get your data
    df = get_price_data(symbol)
    indicators = calculate_indicators(df)
    
    # Get NAMIE analysis
    signal = namie.analyze(df, indicators, symbol)
    
    # Check if NAMIE approves
    if not signal.should_trade:
        print(f"❌ {symbol}: {signal.trade_reason}")
        continue
    
    # Your existing entry logic
    if your_entry_logic(df, indicators):
        # Adjust position size with NAMIE
        base_size = calculate_position_size()
        adjusted_size = namie.adjust_position_size(signal, base_size)
        
        # Execute trade
        result = execute_trade(symbol, adjusted_size)
        
        # Record result for NAMIE learning
        if result:
            namie.record_trade_result(
                signal, result.entry, result.exit, 
                result.side, result.size, result.commission
            )
```

## Step 3: Configuration (Optional)

### Via Environment Variables

Add to `.env`:
```bash
NAMIE_ENABLED=true
NAMIE_MIN_TREND_STRENGTH=40
NAMIE_MAX_CHOP_SCORE=60
```

### Via Python Dict

```python
config = {
    'min_trend_strength': 40,
    'max_chop_score': 60,
    'min_regime_confidence': 0.6,
}

namie = NAMIEIntegration(config=config)
```

## Step 4: Monitor Performance

```python
# Get performance summary
summary = namie.get_performance_summary()

# Print regime performance
for regime, stats in summary['namie_core'].items():
    print(f"{regime}:")
    print(f"  Win Rate: {stats['win_rate']:.1%}")
    print(f"  Total PnL: ${stats['total_pnl']:.2f}")
    print(f"  Trades: {stats['trades']}")
```

## Integration Examples

### Example 1: Add to Existing Strategy

```python
class YourExistingStrategy:
    def __init__(self):
        # Your existing code
        self.namie = NAMIEIntegration()  # ← Add this
    
    def should_enter(self, symbol, df):
        # Your existing logic
        base_signal = self.check_your_conditions(df)
        
        # Add NAMIE check ← Add this
        indicators = self.calculate_indicators(df)
        namie_signal = self.namie.analyze(df, indicators, symbol)
        
        # Combine signals ← Add this
        return base_signal and namie_signal.should_trade
```

### Example 2: APEX v7.1 Enhancement

```python
from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
from bot.namie_integration import NAMIEIntegration

strategy = NIJAApexStrategyV71()
namie = NAMIEIntegration()

# In trading loop
analysis = strategy.analyze_market(df, symbol, balance)

if analysis['action'] != 'hold':
    # Get NAMIE opinion
    signal = namie.analyze(df, analysis['indicators'], symbol)
    
    # Enhance with NAMIE
    if signal.should_trade:
        # Adjust position size
        analysis['position_size'] *= signal.position_size_multiplier
    else:
        # NAMIE blocks trade
        analysis['action'] = 'hold'
        analysis['reason'] = signal.trade_reason
```

## What NAMIE Does For You

### 1. Blocks Choppy Markets
```python
# NAMIE detects and blocks choppy/sideways markets
# Saves you from whipsaw losses

signal = namie.analyze(df, indicators, "ETH-USD")
# If chop_score > 60: signal.should_trade = False
```

### 2. Adjusts Position Sizes
```python
# NAMIE increases size in trending markets
# NAMIE reduces size in volatile/ranging markets

signal = namie.analyze(df, indicators, "BTC-USD")
# Trending: position_size_multiplier = 1.2 (20% larger)
# Ranging: position_size_multiplier = 0.8 (20% smaller)
# Volatile: position_size_multiplier = 0.7 (30% smaller)
```

### 3. Adapts Entry Criteria
```python
# NAMIE adjusts required entry score based on regime

signal = namie.analyze(df, indicators, "SOL-USD")
# Trending: min_entry_score = 3 (easier to enter)
# Ranging/Volatile: min_entry_score = 4 (more selective)
```

### 4. Switches Strategies
```python
# NAMIE automatically selects best strategy per regime

signal = namie.analyze(df, indicators, "AVAX-USD")
# Trending → Trend Following strategy
# Ranging → Mean Reversion strategy  
# Volatile → Breakout strategy
```

## Common Use Cases

### Use Case 1: Filter Out Bad Trades

```python
# Before executing any trade, check with NAMIE
if namie.analyze(df, indicators, symbol).should_trade:
    execute_your_trade()
else:
    skip_trade()  # NAMIE detected unfavorable conditions
```

### Use Case 2: Optimize Position Sizing

```python
signal = namie.analyze(df, indicators, symbol)
base_size = account_balance * 0.05  # Your 5% risk
optimal_size = namie.adjust_position_size(signal, base_size)
# NAMIE adjusts based on market conditions
```

### Use Case 3: Improve Entry Timing

```python
signal = namie.analyze(df, indicators, symbol)
rsi_ranges = namie.get_adaptive_rsi_ranges(signal)

# Use adaptive RSI ranges instead of fixed 30/70
if rsi_ranges['long_min'] < rsi < rsi_ranges['long_max']:
    enter_long()  # Dynamic range based on regime
```

## Reading NAMIE Signals

```python
signal = namie.analyze(df, indicators, "BTC-USD")

# Key metrics to check:
print(f"Regime: {signal.regime.value}")           # TRENDING/RANGING/VOLATILE
print(f"Confidence: {signal.regime_confidence:.0%}") # How confident (>60% good)
print(f"Trend: {signal.trend_strength}/100")      # Trend strength (>40 good)
print(f"Chop: {signal.chop_score:.0f}/100")       # Chop level (<60 good)
print(f"Strategy: {signal.optimal_strategy.value}") # Best strategy
print(f"Should Trade: {signal.should_trade}")     # Final decision
print(f"Reason: {signal.trade_reason}")           # Why/why not
```

## Adjusting Sensitivity

### More Conservative (Fewer Trades, Higher Quality)

```python
config = {
    'min_regime_confidence': 0.7,   # Higher confidence required
    'min_trend_strength': 60,       # Stronger trends only
    'max_chop_score': 50,           # More aggressive chop filtering
}
namie = NAMIEIntegration(config=config)
```

### More Aggressive (More Trades, Lower Quality)

```python
config = {
    'min_regime_confidence': 0.5,   # Lower confidence OK
    'min_trend_strength': 30,       # Weaker trends OK
    'max_chop_score': 70,           # Allow more chop
}
namie = NAMIEIntegration(config=config)
```

## Testing NAMIE

```python
# Test on single symbol
symbol = "BTC-USD"
df = get_historical_data(symbol, days=30)
indicators = calculate_indicators(df)

signal = namie.analyze(df, indicators, symbol)

print("=== NAMIE Analysis ===")
print(f"Symbol: {symbol}")
print(f"Regime: {signal.regime.value} ({signal.regime_confidence:.0%} confidence)")
print(f"Trend Strength: {signal.trend_strength}/100 ({signal.trend_strength_category.value})")
print(f"Chop Score: {signal.chop_score:.0f}/100 ({signal.chop_condition.value})")
print(f"Volatility: {signal.volatility_regime.value} ({signal.volatility_cluster})")
print(f"Strategy: {signal.optimal_strategy.value}")
print(f"Decision: {'✅ TRADE' if signal.should_trade else '❌ SKIP'}")
print(f"Reason: {signal.trade_reason}")
print(f"Position Multiplier: {signal.position_size_multiplier:.2f}x")
```

## Next Steps

1. **Start with conservative settings** - Test with high thresholds
2. **Monitor for 1-2 weeks** - Let NAMIE collect performance data
3. **Review performance** - Check which regimes perform best
4. **Adjust thresholds** - Fine-tune based on your results
5. **Enable strategy switching** - Once confident with performance

## Full Documentation

See [NAMIE_DOCUMENTATION.md](NAMIE_DOCUMENTATION.md) for:
- Complete API reference
- Advanced configuration
- Strategy switching details
- Performance optimization
- Troubleshooting guide

## Support

Questions? Check:
1. This quick start guide
2. [NAMIE_DOCUMENTATION.md](NAMIE_DOCUMENTATION.md)
3. Code comments in `bot/namie_core.py`
4. Example integrations above

---

**Get started in minutes. See results in days. Maximum ROI.** 🚀
