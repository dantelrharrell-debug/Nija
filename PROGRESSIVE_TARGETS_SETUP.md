# Progressive Profit Targets Setup Guide

## Overview
The progressive profit target system helps you grow your trading goals systematically by starting with achievable daily targets and automatically increasing them as you succeed.

## How It Works

### Progressive Target Levels
- **Starting Target**: $25/day
- **Increment**: $25 per level
- **Final Goal**: $1000/day

The system automatically tracks your daily profits and advances to the next target level when you achieve the current one.

### Example Progression
1. Start: $25/day target → Achieve $25+ in one day
2. Level up: $50/day target → Achieve $50+ in one day
3. Level up: $75/day target → Achieve $75+ in one day
4. ... continues in $25 increments ...
5. Goal reached: $1000/day target

## Features

### 1. Automatic Target Advancement
- Tracks daily profits automatically
- Advances to next target when current target is achieved
- Persistent storage - progress saved across bot restarts
- Achievement notifications in logs

### 2. Position Size Scaling
Position sizes automatically adjust based on your current target level:
- **Level 1 ($25/day)**: 1.0x base position size
- **Level 10 ($250/day)**: 1.25x base position size
- **Level 20 ($500/day)**: 1.4x base position size
- **Level 40 ($1000/day)**: 1.5x base position size

This gradual scaling helps you manage risk while growing your positions with your success.

### 3. Performance Tracking
The system tracks:
- Current target level
- Days at current level
- Best daily profit achieved at each level
- Number of times each target was achieved
- Overall progress toward $1000/day goal

## Configuration

### Basic Setup

The progressive target manager is automatically initialized when the bot starts. No configuration is required for basic usage.

### Optional Configuration

You can customize the behavior through environment variables:

```bash
# Set initial capital (used for position sizing)
export INITIAL_CAPITAL=100

# Set capital allocation strategy
export ALLOCATION_STRATEGY=conservative  # or risk_adjusted, equal_weight
```

### Advanced Configuration

To enable exchange-specific risk profiles in the risk manager:

```python
# In your trading strategy initialization
from risk_manager import AdaptiveRiskManager

# Enable exchange profiles
risk_manager = AdaptiveRiskManager(use_exchange_profiles=True)
```

## Monitoring Progress

### Check Current Target

The current target is displayed in the bot logs at startup:

```
======================================================================
✅ Advanced Trading Features Enabled:
   📈 Progressive Targets: $50.00/day
   🏦 Exchange Profiles: Loaded
   💰 Capital Allocation: conservative
======================================================================
```

### Daily Progress

At the end of each trading day, the system logs:
- Current target
- Daily profit/loss
- Progress toward target
- Days at current level

### Manual Status Check

You can check progress programmatically:

```python
from progressive_target_manager import get_progressive_target_manager

manager = get_progressive_target_manager()

# Get current target
current_target = manager.get_current_target()
print(f"Current daily target: ${current_target:.2f}")

# Get progress summary
summary = manager.get_progress_summary()
print(summary)

# Get position size multiplier
multiplier = manager.get_position_size_multiplier()
print(f"Position size multiplier: {multiplier:.2f}x")
```

## Data Storage

Progress is saved in JSON files in the `data/` directory:
- `data/progressive_targets.json` - Target progression history
- `data/capital_allocation.json` - Capital allocation state

These files persist across bot restarts, so your progress is never lost.

## Best Practices

### 1. Start Conservative
The system starts at $25/day for a reason - it's achievable with small accounts. Don't try to skip levels or force rapid progression.

### 2. Be Patient
Some levels may take days or weeks to achieve. This is normal and healthy. The system is designed for sustainable growth, not quick wins.

### 3. Monitor Fee Impact
With small accounts (<$30), exchange fees can consume most profits. The system will still work, but profitability may be limited until you reach higher capital levels.

### 4. Track Overall Progress
Focus on your overall trajectory, not individual days. Some days will be below target, and that's okay.

### 5. Use End-of-Day Processing
The bot includes an `process_end_of_day()` method that should be called daily to:
- Check target achievement
- Update progress tracking
- Generate daily reports

## Troubleshooting

### Target Not Advancing

If you achieved your target but it's not advancing:
1. Check that `process_end_of_day()` is being called
2. Verify the date - targets advance based on calendar days
3. Check logs for any errors during target updates

### Progress Reset

If progress appears to have reset:
1. Check for `data/progressive_targets.json` file
2. Verify file permissions (should be readable/writable)
3. Check logs for file I/O errors

### Position Sizes Too Small

If position sizes are too small even at higher levels:
1. Check `INITIAL_CAPITAL` setting
2. Verify capital allocation is updating correctly
3. Ensure exchange-specific limits aren't constraining positions

## Integration with Other Features

### Exchange-Specific Risk Profiles

Progressive targets work seamlessly with exchange-specific risk profiles:
- Position sizes account for exchange fee structures
- Stop-loss and take-profit targets are exchange-optimized
- Capital allocation considers exchange characteristics

### Multi-Exchange Trading

When trading across multiple exchanges:
- Targets apply to total daily profit across all exchanges
- Position sizes scale appropriately for each exchange
- Progress tracking is unified

### Risk Management

Progressive targets enhance risk management:
- Automatic position scaling prevents over-leveraging
- Conservative growth path reduces drawdown risk
- Achievement-based advancement ensures proven capability

## Example Integration

Here's how the progressive targets integrate into your trading flow:

```python
from trading_strategy import TradingStrategy

# Initialize strategy (progressive targets auto-enabled)
strategy = TradingStrategy()

# Run trading cycle
strategy.run_cycle()

# After a completed trade
strategy.record_trade_with_advanced_manager(
    symbol="BTC-USD",
    profit_usd=15.50,
    is_win=True
)

# At end of day (run once daily)
strategy.process_end_of_day()
```

## Success Metrics

Track these metrics to measure your progress:

1. **Days to Next Level**: How long it takes to achieve each target
2. **Achievement Rate**: Percentage of days where target is met
3. **Average Daily Profit**: Your average across all trading days
4. **Best Daily Performance**: Peak profit at each level
5. **Consistency**: How often you achieve target at each level

## Support

For issues or questions:
1. Check logs first - most issues are logged with detailed messages
2. Verify configuration matches this guide
3. Test with small capital first before scaling up
4. Review the test suite in `bot/tests/test_advanced_integration.py`

## Summary

The progressive profit target system provides:
- ✅ Structured growth path from $25/day to $1000/day
- ✅ Automatic target advancement based on achievement
- ✅ Position size scaling with success
- ✅ Persistent progress tracking
- ✅ Integration with exchange profiles and risk management
- ✅ Comprehensive logging and monitoring

Start small, be patient, and let the system guide your growth to sustainable profitability.
