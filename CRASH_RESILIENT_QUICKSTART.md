# Crash-Resilient Infrastructure - Quick Start Guide

**Status:** ✅ READY FOR USE  
**Version:** 1.0  
**Date:** February 16, 2026

---

## 🚀 Quick Start (5 Minutes)

### 1. Basic Usage

```python
from bot.crash_resilient_trading_integration import get_crash_resilient_trader

# Initialize trader
trader = get_crash_resilient_trader(broker_client, config)

# Validate a trade
result = trader.validate_trade(
    symbol='BTC-USD',
    side='buy',
    position_value=1000,
    market_data=market_data,
    indicators=indicators,
    portfolio_state=portfolio_state
)

if result.approved:
    # Execute trade
    print(f"✅ Trade approved: {result.reason}")
else:
    print(f"❌ Trade blocked: {result.reason}")
```

### 2. With APEX Strategy

```python
from bot.apex_crash_resilient_integration import ApexCrashResilientStrategy

# Initialize strategy
strategy = ApexCrashResilientStrategy(broker_client, config)

# Check entry
can_enter, score, reason, params = strategy.check_long_entry(
    symbol='BTC-USD',
    df=price_data,
    indicators=indicators,
    portfolio_state=portfolio_state
)

if can_enter:
    position_value = params['position_value']
    # Execute trade with adjusted parameters
```

### 3. Monitor Health

```python
# Get infrastructure status
status = trader.get_infrastructure_status()

print(f"Health: {status['health']}")
print(f"Market Regime: {status['metrics']['market_regime']}")
print(f"Resilience Score: {status['metrics']['resilience_score']}")
```

---

## 📋 The Five Pillars

| Pillar | Status | Description |
|--------|--------|-------------|
| 🎯 Portfolio Super-State | Available | Portfolio-level state management |
| 📊 Market Regime Detection | ✅ Active | Adaptive strategy parameters |
| 🎨 Sector Concentration Caps | Available | Diversification enforcement |
| 💧 Liquidity Throttling | Available | Position size adjustment |
| 💥 Crash Simulation | ✅ Active | Resilience validation |

**Note:** "Available" means module exists but may need additional setup. "Active" means currently loaded and working.

---

## 🔧 Configuration

### Basic Config

```python
config = {
    'enabled': True,
    'crash_validation_interval_hours': 24,
}
```

### Advanced Config

```python
config = {
    # Master switch
    'enabled': True,
    
    # Crash validation
    'crash_validation_interval_hours': 24,
    
    # Market regime
    'trending_adx_min': 25,
    'ranging_adx_max': 20,
    
    # Sector caps
    'sector_soft_limit_pct': 15,
    'sector_hard_limit_pct': 20,
    
    # Liquidity
    'min_liquidity_score': 0.3,
    'liquidity_throttle_threshold': 0.6,
}
```

---

## 📊 What Gets Validated

### Pre-Trade Checks

1. **Portfolio State** - Is portfolio in safe state? (NORMAL, CAUTIOUS, etc.)
2. **Market Regime** - What regime are we in? (TRENDING, RANGING, VOLATILE)
3. **Sector Caps** - Would this exceed sector limits?
4. **Liquidity** - Is there enough liquidity?
5. **Score Requirements** - Does entry meet regime-adjusted score?

### Automatic Adjustments

- **Position Size** - Multiplied by regime factor (0.7x - 1.2x)
- **Entry Score** - Adjusted based on regime (3-5 conditions required)
- **Liquidity Throttle** - Reduced if liquidity low
- **Stop Distance** - Adjusted for regime volatility

---

## 🎯 Integration Points

### Where to Add Checks

```python
# In your trading strategy, before executing a trade:

# 1. Check APEX entry logic
can_enter_apex, score, reason = check_apex_entry(...)

if not can_enter_apex:
    return False

# 2. Validate through crash-resilient infrastructure
validation = trader.validate_trade(...)

if not validation.approved:
    return False

# 3. Apply adjusted parameters
position_value = trader.adjust_position_size(base_value, validation)
min_score = trader.get_regime_adjusted_entry_score(3, validation)

# 4. Execute with safety
execute_trade(position_value, ...)
```

---

## 🚨 Emergency Mode

### Activate Emergency Halt

```python
# Halt all trading immediately
trader.activate_emergency_mode("Market crash detected")
```

### Deactivate Emergency

```python
# Resume normal operations
trader.deactivate_emergency_mode()
```

### Check Emergency Status

```python
status = trader.get_infrastructure_status()
if status['emergency_mode']:
    print(f"Emergency: {status['emergency_reason']}")
```

---

## 🔍 Monitoring

### Infrastructure Health

```python
trader = get_crash_resilient_trader()
status = trader.get_infrastructure_status()

# Check overall health
print(f"Health: {status['health']}")  # healthy, degraded, stressed, critical

# Check metrics
metrics = status['metrics']
print(f"Portfolio State: {metrics['portfolio_state']}")
print(f"Market Regime: {metrics['market_regime']}")
print(f"Resilience Score: {metrics['resilience_score']}")
```

### Validation Statistics

```python
stats = trader.get_validation_statistics()
print(f"Approval Rate: {stats['approval_rate']:.1f}%")
print(f"Total Validations: {stats['total_validations']}")
print(f"Trades Blocked: {stats['rejected_count']}")
```

### Crash Validation

```python
# Run crash simulation
if trader.should_run_crash_validation():
    passed, results = trader.run_crash_validation(
        portfolio_state=current_portfolio,
        stress_level='moderate'  # mild, moderate, severe
    )
    
    if not passed:
        print(f"⚠️ Failed crash simulation")
        print(f"Max drawdown: {results['max_drawdown']}%")
```

---

## 📈 Market Regimes

### TRENDING
- ADX > 25
- Position size: **1.2x** (aggressive)
- Entry score: **3/5** minimum
- RSI ranges: Wider for momentum

### RANGING  
- ADX < 20
- Position size: **0.8x** (conservative)
- Entry score: **4/5** minimum
- RSI ranges: Narrower for mean reversion

### VOLATILE
- ADX 20-25, high ATR
- Position size: **0.7x** (defensive)
- Entry score: **4/5** minimum
- RSI ranges: Tight for quality

---

## 🎨 Sector Limits

### Default Limits

- **Soft Limit:** 15% per sector (warning)
- **Hard Limit:** 20% per sector (block trade)
- **Critical:** 30%+ (force reduction)

### Supported Sectors

- Layer 1 (BTC, ETH, SOL, etc.)
- Layer 2 (MATIC, ARB, OP, etc.)
- DeFi (UNI, AAVE, COMP, etc.)
- Meme Coins (DOGE, SHIB, etc.)
- And more...

---

## 💧 Liquidity Scoring

### Score Calculation

```
Liquidity Score = (Spread Score × 0.6) + (Volume Score × 0.4)

Where:
- Spread Score = 1.0 - (spread_pct / 1.0%)
- Volume Score = current_volume / avg_volume
```

### Throttling Rules

| Score | Action |
|-------|--------|
| < 0.3 | ❌ Block trade |
| 0.3 - 0.6 | ⚠️ Reduce position size |
| > 0.6 | ✅ Allow full position |

---

## 💥 Crash Scenarios

### Tested Scenarios

1. **Flash Crash** - 25% sudden drop
2. **Gradual Decline** - 15% slow bear market
3. **Black Swan** - 35% extreme volatility
4. **Sector Crash** - 50% sector-specific
5. **Contagion** - Cascading failures
6. **Liquidity Crisis** - 70% liquidity reduction

### Target Resilience

- Max acceptable drawdown: **< 50%**
- Resilience score: **> 0.6**
- Validation frequency: **Every 24 hours**

---

## ✅ Checklist

### Before Going Live

- [ ] Test institutional coordinator loads
- [ ] Test crash-resilient trader works
- [ ] Integrate with your trading strategy
- [ ] Configure sector limits
- [ ] Set crash validation schedule
- [ ] Test emergency mode
- [ ] Monitor health metrics
- [ ] Run crash simulation

### During Operation

- [ ] Monitor infrastructure health
- [ ] Check validation approval rates
- [ ] Review rejected trades
- [ ] Run periodic crash validation
- [ ] Adjust thresholds as needed

---

## 🐛 Troubleshooting

### Components Not Loading

**Symptom:** Components show as "not available"

**Solution:**
- Check module dependencies installed
- Verify module paths correct
- Some components are optional

### Low Approval Rate

**Symptom:** Many trades blocked

**Solution:**
- Review rejection reasons
- Check if in CRISIS/STRESSED state
- Verify sector limits not too tight
- Check liquidity thresholds

### Emergency Mode Stuck

**Symptom:** Can't resume trading

**Solution:**
```python
trader.deactivate_emergency_mode()
```

---

## 📚 Resources

### Documentation
- `CRASH_RESILIENT_INFRASTRUCTURE.md` - Complete guide
- `test_crash_resilient_infrastructure.py` - Test suite
- `apex_crash_resilient_integration.py` - Integration example

### Module Files
- `bot/institutional_infrastructure_coordinator.py` - Core coordinator
- `bot/crash_resilient_trading_integration.py` - Trading interface
- `bot/portfolio_super_state_machine.py` - Portfolio states
- `bot/market_regime_detector.py` - Regime detection
- `bot/sector_cap_state.py` - Sector limits
- `bot/liquidity_routing_system.py` - Liquidity checks
- `bot/market_crash_simulator.py` - Crash simulation

---

## 🎓 Examples

### Simple Integration

```python
from bot.crash_resilient_trading_integration import get_crash_resilient_trader

trader = get_crash_resilient_trader()

# Before each trade
result = trader.validate_trade(
    symbol='BTC-USD',
    side='buy',
    position_value=1000,
    market_data={'close': 50000, 'volume': 1000000}
)

if result.approved:
    execute_trade()
```

### Full APEX Integration

See `bot/apex_crash_resilient_integration.py` for complete example.

---

## 🚀 Next Steps

1. **Test** - Run `python test_crash_resilient_infrastructure.py`
2. **Integrate** - Add to your trading strategy
3. **Monitor** - Watch health metrics
4. **Optimize** - Tune thresholds for your needs
5. **Scale** - Deploy to production

---

**Status:** ✅ READY FOR PRODUCTION  
**Support:** See documentation for details  
**Version:** 1.0 - February 16, 2026

*"Crash-resilient infrastructure for institutional-grade trading."* 🏛️
