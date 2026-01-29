# GMIG Quick Start Guide

## 🚀 Get Started in 5 Minutes

### 1. Installation

GMIG is already included in NIJA. No additional installation required!

```bash
# Verify installation
python -c "from bot.gmig import GMIGEngine; print('✓ GMIG installed')"
```

### 2. Optional: Setup FRED API (Recommended)

For enhanced central bank data:

```bash
# Get free API key from: https://fred.stlouisfed.org/docs/api/api_key.html

# Add to .env file
echo "FRED_API_KEY=your_api_key_here" >> .env
```

### 3. Run Your First Analysis

```python
from bot.gmig import GMIGEngine

# Initialize GMIG
gmig = GMIGEngine()

# Run full analysis
report = gmig.run_full_analysis()

# View results
print(f"Regime: {report['macro_regime']['regime']}")
print(f"Signal: {report['positioning_signals']['primary_signal']}")
print(f"Alert: {report['crisis_assessment']['alert_level']}")
```

### 4. Run Tests

```bash
# Test the entire GMIG system
python test_gmig.py
```

Expected output:
```
Tests Passed: 6/6
✓ PASS  Central Bank Monitor
✓ PASS  Interest Rate Analyzer
✓ PASS  Yield Curve Modeler
✓ PASS  Liquidity Stress Detector
✓ PASS  Crisis Warning System
✓ PASS  GMIG Engine (Full)

🎉 ALL TESTS PASSED - GMIG is operational!
```

### 5. Integrate with Your Trading Bot

```python
from bot.gmig import GMIGEngine
from bot.trading_strategy import TradingStrategy

# Initialize both systems
gmig = GMIGEngine()
strategy = TradingStrategy()

# Get macro intelligence
macro_report = gmig.run_full_analysis()

# Adjust trading based on macro regime
regime = macro_report['macro_regime']['regime']
risk_adj = macro_report['risk_adjustments']

# Apply risk adjustments
if regime == 'crisis':
    # Emergency defensive mode
    strategy.stop_all_new_trades()
    strategy.reduce_positions(multiplier=0.20)
elif regime == 'pre_recession':
    # Defensive mode
    strategy.reduce_positions(multiplier=0.50)
elif regime == 'risk_on':
    # Aggressive mode
    strategy.increase_exposure(multiplier=1.20)

# Apply position size adjustments
position_multiplier = risk_adj['position_size_multiplier']
strategy.set_position_size_multiplier(position_multiplier)
```

## 📊 Common Use Cases

### Use Case 1: Daily Macro Check

```python
from bot.gmig import GMIGEngine
import schedule

gmig = GMIGEngine()

def daily_macro_check():
    """Run daily at market open"""
    report = gmig.run_full_analysis()

    # Log to file or database
    with open('gmig_daily_log.txt', 'a') as f:
        f.write(f"{report['timestamp']}: {report['summary']}\n")

    # Send alert if crisis warning
    if report['crisis_assessment']['alert_level'] in ['orange', 'red']:
        send_alert(f"⚠️ GMIG Alert: {report['summary']['key_recommendation']}")

# Schedule daily at 9:00 AM
schedule.every().day.at("09:00").do(daily_macro_check)
```

### Use Case 2: Crisis Monitoring

```python
from bot.gmig import GMIGEngine
import time

gmig = GMIGEngine()

def monitor_crisis():
    """Monitor for crisis signals every 5 minutes"""
    while True:
        crisis_check = gmig.run_crisis_check()

        if crisis_check['action_required']:
            print(f"🚨 ALERT: {crisis_check['alert_level']}")
            print(f"Crisis Probability: {crisis_check['crisis_probability']:.1%}")
            # Take defensive action

        time.sleep(300)  # 5 minutes

# Run in background
import threading
monitor_thread = threading.Thread(target=monitor_crisis, daemon=True)
monitor_thread.start()
```

### Use Case 3: Component-Specific Analysis

```python
from bot.gmig import YieldCurveAIModeler, LiquidityStressDetector

# Just yield curve analysis
yc = YieldCurveAIModeler()
yc_data = yc.analyze_curve()

if yc_data['recession_probability'] > 0.50:
    print("⚠️ High recession probability - reduce risk")

# Just liquidity monitoring
liquidity = LiquidityStressDetector()
liq_data = liquidity.detect_stress()

if liq_data['overall_stress_level'] == 'red':
    print("🚨 Liquidity crisis - emergency defensive")
```

## 🎯 Understanding Outputs

### Macro Regimes

| Regime | What It Means | Your Action |
|--------|---------------|-------------|
| `crisis` | Financial crisis active | Move to cash/safe havens |
| `pre_recession` | Recession likely in 6-18mo | Reduce risk, increase cash |
| `risk_off` | Market stress elevated | Defensive positioning |
| `tightening` | Central banks raising rates | Cautious, favor value |
| `easing` | Central banks cutting rates | Bullish for risk assets |
| `risk_on` | Favorable conditions | Aggressive positioning |
| `transitional` | Mixed signals | Balanced approach |

### Alert Levels

| Level | Crisis Prob | Action |
|-------|-------------|--------|
| 🟢 Green | < 20% | Normal operations |
| 🟡 Yellow | 20-40% | Increase monitoring |
| 🟠 Orange | 40-60% | Reduce positions 50% |
| 🔴 Red | > 60% | Emergency defensive |

### Positioning Signals

| Signal | Meaning | Position Size |
|--------|---------|---------------|
| `maximum_defensive` | Crisis mode | 20% of normal |
| `reduce_risk` | High risk | 50% of normal |
| `defensive` | Elevated risk | 70% of normal |
| `cautious` | Moderate risk | 75% of normal |
| `neutral` | Balanced | 100% (normal) |
| `bullish` | Favorable | 120% of normal |
| `aggressive` | Strong conditions | 150% of normal |

## 🔧 Configuration Options

### Engine Modes

```python
# Full mode (all features, default)
gmig = GMIGEngine(config={'mode': 'full'})

# Essential mode (core features only, faster)
gmig = GMIGEngine(config={'mode': 'essential'})

# Crisis-only mode (just crisis detection)
gmig = GMIGEngine(config={'mode': 'crisis_only'})
```

### Intelligence Levels

```python
# Ultra (most advanced, default)
gmig = GMIGEngine(config={'intelligence_level': 'ultra'})

# Advanced (good balance)
gmig = GMIGEngine(config={'intelligence_level': 'advanced'})

# Standard (faster, less sophisticated)
gmig = GMIGEngine(config={'intelligence_level': 'standard'})
```

### Update Frequency

```python
gmig = GMIGEngine(config={
    'update_frequency_minutes': 15,      # Full analysis every 15 min
    'crisis_check_frequency_minutes': 5  # Crisis check every 5 min
})
```

## 📈 Performance Tips

1. **Run Full Analysis Sparingly:** Every 15-60 minutes is sufficient
2. **Use Crisis Checks for Monitoring:** Every 5 minutes for real-time alerts
3. **Cache Results:** Store reports and reuse for a few minutes
4. **Parallel Components:** Individual components can run in parallel
5. **FRED API:** Set up for better central bank data quality

## 🎓 Learning Path

### Beginner (Day 1)
1. Run `test_gmig.py` to verify setup
2. Run simple analysis and understand output
3. Review GMIG_DOCUMENTATION.md overview

### Intermediate (Week 1)
1. Integrate crisis checks into trading bot
2. Set up daily macro analysis
3. Study historical regimes and outcomes

### Advanced (Month 1)
1. Customize risk adjustments based on regime
2. Build multi-account orchestration
3. Create investor-grade reporting

### Expert (Month 3+)
1. Add custom indicators
2. Tune AI models for your markets
3. Build predictive regime transitions

## 🆘 Troubleshooting

### "No FRED API key" warning
- Optional: Get free key at https://fred.stlouisfed.org/docs/api/api_key.html
- Add to `.env`: `FRED_API_KEY=your_key`
- System works without it (uses cached/simulated data)

### Analysis taking too long
- Use `mode='essential'` for faster analysis
- Reduce update frequency
- Use crisis checks instead of full analysis

### Unexpected regime detection
- Check individual component outputs
- Review confidence scores
- Compare to market conditions
- Regimes can change quickly in volatile markets

## 📞 Next Steps

1. **Read Full Documentation:** [GMIG_DOCUMENTATION.md](GMIG_DOCUMENTATION.md)
2. **Study Examples:** Review test cases in `test_gmig.py`
3. **Integrate:** Add to your trading strategy
4. **Monitor:** Track regime changes and outcomes
5. **Optimize:** Tune based on your risk tolerance

## 💡 Pro Tips

- **Act on Red Alerts:** They're rare but critical
- **Log Everything:** Track regime changes and performance
- **Backtest Regimes:** Study historical regime transitions
- **Combine with MMIN:** Use both for complete intelligence
- **Trust the System:** GMIG uses proven academic research

---

**Ready to start?** Run `python test_gmig.py` now! 🚀
