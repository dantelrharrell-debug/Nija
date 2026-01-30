# Micro Capital Mode & Auto-Scaling Guide

## Overview

NIJA's Micro Capital Mode is optimized for accounts starting from $15 and automatically scales configuration as your balance grows. The auto-scaling system automatically upgrades your trading parameters at key thresholds, unlocking more features and positions as you grow your account.

## Features

### 🚀 Auto-Scaling Tiers

Your configuration automatically upgrades through four tiers:

| Tier | Equity Range | Positions | Risk/Trade | Copy Trading | Leverage |
|------|-------------|-----------|------------|--------------|----------|
| **STARTER** | $15 - $249 | 2 | 3% | ❌ | ❌ |
| **GROWTH** | $250 - $499 | 3 | 4% | ❌ | ❌ |
| **ADVANCED** | $500 - $999 | 4 | 4% | ✅ | ❌ |
| **ELITE** | $1000+ | 6 | 5% | ✅ | ✅ |

### 💎 Core Configuration

All tiers include:
- **Market Regime Engine**: Advanced market analysis
- **Signal Ensemble**: Multiple signal confirmation
- **AI Trade Filter**: Machine learning trade validation
- **Ultra-Conservative Risk Management**: 6% daily loss limit, 12% max drawdown
- **Multi-Broker Support**: Coinbase (primary) + Kraken (secondary)
- **Smart Position Sizing**: Hybrid Kelly/Volatility/Equity approach

## Quick Start

### Option 1: Using Environment File

1. **Copy the template:**
   ```bash
   cp .env.micro_capital .env
   ```

2. **Add your API credentials** in `.env`:
   ```bash
   # Coinbase
   COINBASE_API_KEY=organizations/YOUR_ORG/apiKeys/YOUR_KEY
   COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----..."
   
   # Kraken (optional)
   KRAKEN_MASTER_API_KEY=your-key
   KRAKEN_MASTER_API_SECRET=your-secret
   ```

3. **Start the bot:**
   ```bash
   python bot.py
   ```

### Option 2: Using Python API

```python
from bot.auto_scaling_config import auto_scale, get_scaling_summary

# Get your current balance
current_balance = 250.0  # Example: $250

# Apply auto-scaling configuration
scaled, old_tier, new_tier = auto_scale(current_balance)

if scaled:
    print(f"🔥 Upgraded from {old_tier} to {new_tier}!")

# View current status
print(get_scaling_summary())
```

### Option 3: Direct Configuration

```python
from bot.micro_capital_config import apply_micro_capital_config

# Apply configuration for your current equity
config = apply_micro_capital_config(equity=500.0, set_env_vars=True)

print(f"Current tier: {config['dynamic_config']}")
print(f"Max positions: {config['dynamic_config']['max_positions']}")
print(f"Copy trading: {config['dynamic_config']['copy_trading']}")
```

## Configuration Parameters

### Operational Settings
- `MICRO_CAPITAL_MODE`: `True` (enables micro capital optimizations)
- `MODE`: `MASTER_ONLY` (single account initially, copy trading at $500+)
- `PRIMARY_BROKER`: `COINBASE`
- `SECONDARY_BROKER`: `KRAKEN`
- `LIVE_TRADING`: `True`
- `PRO_MODE`: `True` (required for efficient capital usage)

### Balance Requirements
- `MIN_BALANCE_TO_TRADE`: $15.00
- `MIN_TRADE_SIZE`: $5.00
- `MIN_BALANCE_COINBASE`: $10.00
- `MIN_BALANCE_KRAKEN`: $50.00

### Risk Management (Starting Tier)
- `MAX_POSITIONS`: 2 (scales to 3/4/6)
- `MAX_POSITION_PCT`: 18% of capital
- `RISK_PER_TRADE`: 3% (scales to 4%/5%)
- `DAILY_MAX_LOSS`: 6%
- `MAX_DRAWDOWN`: 12%

### Position Sizing
- `POSITION_SIZER`: `HYBRID`
- `KELLY_WEIGHT`: 0.30 (30% Kelly criterion)
- `VOLATILITY_WEIGHT`: 0.40 (40% volatility-based)
- `EQUITY_WEIGHT`: 0.30 (30% equity-based)

### Signal Filtering
- `MIN_SIGNAL_SCORE`: 0.75 (75% signal quality required)
- `MIN_AI_CONFIDENCE`: 0.70 (70% AI confidence required)
- `MIN_RISK_REWARD`: 1.8 (minimum 1.8:1 risk/reward)

### Trading Pairs
- `TRADE_ONLY`: `["BTC", "ETH", "SOL"]`
- Only major, liquid cryptocurrencies

### Advanced Features
- `MARKET_REGIME_ENGINE`: `True`
- `SIGNAL_ENSEMBLE`: `True`
- `AI_TRADE_FILTER`: `True`
- `LEVERAGE_ENABLED`: `False` (auto-enabled at $1000+)
- `COPY_TRADING`: `False` (auto-enabled at $500+)

### Safety Features
- `AUTO_SHUTOFF_ON_ERRORS`: `True`
- `MAX_CONSECUTIVE_LOSSES`: 3
- `FORCE_CASH_BUFFER`: 15% (always keep 15% in cash)

## Auto-Scaling Features

### Automatic Tier Detection
```python
from bot.auto_scaling_config import get_auto_scaling_engine

engine = get_auto_scaling_engine()

# Automatically check and scale based on current balance
balance = broker.get_balance()
scaled, old_tier, new_tier = engine.check_and_scale(balance)

if scaled:
    print(f"🔥 AUTO-SCALING: {old_tier.name} → {new_tier.name}")
```

### Progress Tracking
```python
# Get progress to next tier
progress = engine.get_progress_to_next_tier()

if progress:
    print(f"Current: ${progress['current_equity']:.2f}")
    print(f"Next tier: {progress['next_tier']['name']} at ${progress['next_tier']['min_equity']:.2f}")
    print(f"Progress: {progress['progress_pct']:.1f}%")
    print(f"Equity needed: ${progress['equity_needed']:.2f}")
```

### Upgrade History
```python
# View upgrade history
history = engine.state_manager.get_upgrade_history()

for upgrade in history:
    print(f"{upgrade['timestamp']}: {upgrade['from_tier']} → {upgrade['to_tier']} (${upgrade['equity']:.2f})")
```

### Integration with Trading Bot
```python
from bot.auto_scaling_config import integrate_with_broker_manager

# Automatically integrate with your broker manager
success = integrate_with_broker_manager(broker_manager)

# Auto-scaling will now check and apply upgrades based on total balance
```

## State Persistence

Auto-scaling state is saved to `.auto_scaling_state.json` including:
- Current tier
- Last equity check
- Upgrade history
- Last upgrade timestamp

This prevents duplicate notifications and tracks your growth over time.

## Monitoring

### View Current Status
```python
from bot.auto_scaling_config import get_scaling_summary

print(get_scaling_summary())
```

Output:
```
╔══════════════════════════════════════════════════════════════════════════╗
║                     NIJA AUTO-SCALING STATUS                             ║
╚══════════════════════════════════════════════════════════════════════════╝

💰 CURRENT EQUITY: $750.00

🎯 CURRENT TIER: ADVANCED
   • Advanced features with copy trading enabled
   • Max Positions: 4
   • Risk Per Trade: 4.0%
   • Copy Trading: ✅ Enabled
   • Leverage: ❌ Disabled

📈 NEXT TIER: ELITE
   • Unlocks at: $1000.00
   • Progress: 75.0%
   • Equity needed: $250.00
```

### Logging

Auto-scaling events are logged:
```
2026-01-30 06:00:00 | INFO | 🔥 AUTO-SCALING UPGRADE: $500.00 → ADVANCED tier
2026-01-30 06:00:00 | INFO |    Max Positions: 4
2026-01-30 06:00:00 | INFO |    Risk Per Trade: 4.0%
2026-01-30 06:00:00 | INFO |    Copy Trading: True
2026-01-30 06:00:00 | INFO |    Leverage: False
```

## Testing

### Test Configuration Import
```bash
python3 -c "from bot.micro_capital_config import MICRO_CAPITAL_CONFIG; print('✅ Config loaded')"
```

### Run Test Suite
```bash
# Test micro capital configuration
python3 scripts/test_micro_capital_config.py

# Test auto-scaling
python3 scripts/test_auto_scaling.py
```

### Interactive Demo
```bash
# View auto-scaling at different equity levels
python3 bot/auto_scaling_config.py
```

## Best Practices

### 1. Start Small
- Begin with minimum $15
- Let auto-scaling upgrade you naturally
- Don't force higher tiers prematurely

### 2. Monitor Progress
- Check scaling status regularly
- Track upgrade history
- Watch for tier transition notifications

### 3. Respect Risk Limits
- Never override daily loss limits
- Keep 15% cash buffer minimum
- Max 3 consecutive losses before pause

### 4. Use Multi-Broker Setup
- Start with Coinbase (min $10)
- Add Kraken at $50+ for lower fees
- Exchange priority: Coinbase → Kraken

### 5. Trust the System
- Auto-scaling knows when to upgrade
- Features unlock when you're ready
- Risk scales appropriately with balance

## Troubleshooting

### "No tier found for equity"
- Ensure equity >= $15
- Check that MICRO_CAPITAL_MODE is enabled

### "Configuration not scaling"
- Verify auto_scale() is being called
- Check .auto_scaling_state.json permissions
- Review logs for scaling events

### "Features not enabling"
- Confirm current tier
- Check if threshold has been reached
- Force scaling: `auto_scale(equity, force=True)`

### "State file issues"
- Delete `.auto_scaling_state.json` to reset
- State will rebuild on next scale check

## Advanced Usage

### Custom Tier Thresholds
```python
from bot.auto_scaling_config import ScalingTier, SCALING_TIERS

# Add custom tier (advanced users only)
custom_tier = ScalingTier(
    name="CUSTOM",
    min_equity=2000.0,
    max_equity=None,
    max_positions=8,
    risk_per_trade=6.0,
    copy_trading=True,
    leverage_enabled=True,
    description="Custom tier for experienced traders"
)

SCALING_TIERS.append(custom_tier)
```

### Manual Override
```python
from bot.micro_capital_config import get_dynamic_config, apply_micro_capital_config

# Get config for specific equity without auto-scaling
config = get_dynamic_config(equity=1500.0)

# Apply without setting environment variables
result = apply_micro_capital_config(equity=1500.0, set_env_vars=False)
```

## Support

For issues or questions:
1. Check logs for auto-scaling events
2. Run test suites to verify configuration
3. Review .auto_scaling_state.json for current tier
4. Check broker balance matches expected equity

## Related Documentation

- `bot/micro_capital_config.py` - Core configuration module
- `bot/auto_scaling_config.py` - Auto-scaling engine
- `.env.micro_capital` - Environment template
- `MICRO_MASTER_GUIDE.md` - Micro capital trading guide

## Summary

Micro Capital Mode + Auto-Scaling provides:
- ✅ Safe starting point at $15
- ✅ Automatic configuration upgrades
- ✅ Progressive feature unlocks
- ✅ Conservative risk management
- ✅ Multi-broker support
- ✅ AI-powered trade filtering
- ✅ Transparent tier progression
- ✅ State persistence
- ✅ Comprehensive testing

**Start small, grow naturally, scale automatically!** 🚀
