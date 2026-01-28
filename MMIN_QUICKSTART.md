# MMIN Quick Start Guide

## 🚀 Getting Started with MMIN in 5 Minutes

### What is MMIN?

MMIN (Multi-Market Intelligence Network) transforms NIJA into a global trading intelligence that learns patterns across crypto, forex, equities, commodities, and bonds.

### Quick Setup

```bash
# 1. Test MMIN installation
python test_mmin.py

# 2. Run integration examples
python mmin_integration_example.py
```

### Basic Usage

```python
from bot.mmin import MMINEngine

# Initialize MMIN
mmin = MMINEngine()

# Analyze all markets
analysis = mmin.analyze_markets(timeframe='1h', limit=200)

# Get results
print(f"Regime: {analysis['macro_regime']['regime'].value}")
print(f"Signals: {len(analysis['signals'])}")
print(f"Allocation: {analysis['capital_allocation']}")
```

### Key Features

#### 1️⃣ Macro Regime Detection

```python
regime = analysis['macro_regime']
print(f"Current: {regime['regime'].value}")
print(f"Confidence: {regime['confidence']:.0%}")

# Trading implications
implications = regime['trading_implications']
print(f"Preferred markets: {implications['preferred_markets']}")
print(f"Position sizing: {implications['position_sizing']}")
```

**Regimes:**
- `risk_on` - Crypto ↑, Equities ↑, Bonds ↓
- `risk_off` - Flight to safety, Bonds ↑
- `inflation` - Commodities ↑, Bonds ↓
- `deflation` - Commodities ↓, Bonds ↑
- `growth` - Equities ↑, Crypto ↑
- `recession` - Everything ↓ except bonds

#### 2️⃣ Cross-Market Signals

```python
# MMIN requires signals to be confirmed across markets
for signal in analysis['signals']:
    if signal['cross_market_confirmations'] >= 2:
        print(f"✓ {signal['symbol']}: {signal['signal_type']}")
        print(f"  Confidence: {signal['confidence']:.0%}")
        print(f"  Confirmations: {signal['cross_market_confirmations']}")
```

#### 3️⃣ Intelligent Capital Allocation

```python
allocation = analysis['capital_allocation']
for market, capital in allocation['allocations'].items():
    pct = (capital / allocation['total_capital']) * 100
    print(f"{market}: ${capital:,.0f} ({pct:.1f}%)")
```

**Allocation Strategies:**
- `fixed` - Pre-defined percentages
- `balanced` - Equal across all markets
- `adaptive` - Dynamic based on performance + regime
- `aggressive` - Concentrate in top performers

#### 4️⃣ Correlation Analysis

```python
correlations = analysis.get('correlations', {})
if correlations and 'significant_pairs' in correlations:
    print("Correlated Assets:")
    for sym1, sym2, corr in correlations['significant_pairs'][:5]:
        print(f"  {sym1} ↔ {sym2}: {corr:.2f}")
```

#### 5️⃣ Transfer Learning

```python
from bot.mmin import TransferLearningEngine

transfer = TransferLearningEngine()

# Learn from crypto
pattern = transfer.learn_pattern(crypto_data, 'crypto', 'breakout', 
                                 outcome={'profit': 0.03, 'win': True})

# Apply to equities
recommendation = transfer.transfer_pattern(pattern, 'equities')
print(f"Confidence: {recommendation['adjusted_confidence']:.0%}")
print(f"Recommended: {recommendation['recommended']}")
```

### Configuration

Edit `bot/mmin/mmin_config.py`:

```python
# Enable/disable MMIN
MMIN_ENGINE_CONFIG = {
    'enabled': True,
    'mode': 'adaptive',  # Your strategy
    'intelligence_level': 'god_mode',
    'cross_market_signals_required': 2,
}

# Markets to monitor
MARKET_CATEGORIES = {
    'crypto': ['BTC-USD', 'ETH-USD', ...],
    'equities': ['SPY', 'QQQ', ...],
    # ... add your symbols
}
```

### Integration with Existing Strategy

```python
# In your trading strategy
from bot.mmin import MMINEngine

class YourStrategy:
    def __init__(self):
        self.mmin = MMINEngine()
    
    def generate_signals(self):
        # Get MMIN analysis
        analysis = self.mmin.analyze_markets()
        regime = analysis['macro_regime']['regime']
        
        # Adjust strategy based on regime
        if regime.value == 'risk_off':
            self.reduce_positions()
            self.tighten_stops()
        elif regime.value == 'risk_on':
            self.increase_positions()
            self.widen_targets()
        
        # Use MMIN signals with cross-market confirmation
        for signal in analysis['signals']:
            if signal['cross_market_confirmations'] >= 2:
                self.execute_trade(signal)
```

### Common Workflows

#### Workflow 1: Conservative Trading

```python
# Only trade when:
# 1. Regime is favorable
# 2. Multiple markets confirm
# 3. High confidence

analysis = mmin.analyze_markets()
regime = analysis['macro_regime']
preferred = regime['trading_implications']['preferred_markets']

for signal in analysis['signals']:
    if (signal['market_type'] in preferred and
        signal['confidence'] >= 0.75 and
        signal['cross_market_confirmations'] >= 3):
        # Execute trade
        pass
```

#### Workflow 2: Adaptive Allocation

```python
# Rebalance portfolio based on MMIN allocation
from bot.mmin import GlobalCapitalRouter

router = GlobalCapitalRouter()

# Get current performance
market_metrics = {
    'crypto': {'sharpe_ratio': 2.1, 'win_rate': 0.62, ...},
    'equities': {'sharpe_ratio': 1.8, 'win_rate': 0.58, ...},
}

# Calculate optimal allocation
allocation = router.calculate_allocation(
    market_metrics,
    macro_regime='growth',
    total_capital=100000
)

# Get rebalancing moves
current = {'crypto': 40000, 'equities': 30000, 'forex': 30000}
moves = router.suggest_rebalance(current, allocation, threshold=0.05)

for market, change in moves.items():
    if change > 0:
        print(f"Add ${change:,.0f} to {market}")
    else:
        print(f"Remove ${-change:,.0f} from {market}")
```

### Performance Monitoring

```python
# Get MMIN status
status = mmin.get_status()

print(f"Intelligence Level: {status['intelligence_level']}")
print(f"Current Regime: {status['current_regime']}")
print(f"Signals Generated: {status['performance']['total_signals']}")
print(f"Learning Stats: {status['learning_stats']}")
```

### Troubleshooting

**Issue:** No signals generated
- Check if markets are configured in `mmin_config.py`
- Verify `cross_market_signals_required` isn't too high
- Ensure regime allows trading in those markets

**Issue:** Low correlation confidence
- Increase data history (limit parameter)
- Check market overlap (some markets trade different hours)

**Issue:** Allocation seems off
- Review `allocation_strategy` in config
- Check market performance metrics
- Verify regime alignment

### Next Steps

1. ✅ Run test suite: `python test_mmin.py`
2. ✅ Review examples: `python mmin_integration_example.py`
3. ✅ Read full docs: `MMIN_DOCUMENTATION.md`
4. 🔄 Customize `mmin_config.py` for your needs
5. 🔄 Integrate with your trading strategy
6. 🔄 Paper trade and monitor performance
7. 🚀 Deploy to production

### Resources

- **Full Documentation:** [MMIN_DOCUMENTATION.md](MMIN_DOCUMENTATION.md)
- **Test Suite:** `test_mmin.py`
- **Integration Examples:** `mmin_integration_example.py`
- **Configuration:** `bot/mmin/mmin_config.py`

---

## 🎯 Pro Tips

1. **Start Conservative:** Use `cross_market_signals_required: 2+` initially
2. **Monitor Regimes:** Track regime transitions for better timing
3. **Diversify:** Use correlation analysis to find low-correlated assets
4. **Adapt Allocation:** Let MMIN adjust capital based on performance
5. **Transfer Learning:** Successful patterns in one market often work in others

---

**MMIN transforms NIJA from a single-market bot into a GLOBAL TRADING INTELLIGENCE**

🧬 Cross-market learning  
🧠 Transfer learning  
📊 Macro forecasting  
💰 Global capital routing  
🔗 Correlation intelligence  

**You're ready to trade like a global hedge fund!** 🚀
