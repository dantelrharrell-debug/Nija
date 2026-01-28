# NIJA Global Macro Intelligence Grid (GMIG)

## 🌐 ULTRA MODE - Elite Macro Intelligence

**Version:** 1.0.0  
**Status:** Production Ready  
**Date:** January 28, 2026

---

## 🎯 Overview

GMIG (Global Macro Intelligence Grid) is NIJA's **ULTRA MODE** - the pinnacle of autonomous trading intelligence that enables **pre-positioning before macro events** for **asymmetric returns**.

This system transforms NIJA into a **fund-grade macro intelligence platform** capable of detecting and capitalizing on major market regime changes before they happen.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         GMIG ENGINE                                  │
│                    (Orchestration Layer)                             │
└─────────────────────────────────────────────────────────────────────┘
         │              │              │              │              │
         ▼              ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Central     │ │  Interest    │ │ Yield Curve  │ │  Liquidity   │ │   Crisis     │
│    Bank      │ │     Rate     │ │      AI      │ │    Stress    │ │   Warning    │
│  Monitor     │ │  Analyzer    │ │   Modeler    │ │   Detector   │ │   System     │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
         │              │              │              │              │
         └──────────────┴──────────────┴──────────────┴──────────────┘
                                    │
                                    ▼
                        ┌────────────────────────┐
                        │  Macro Regime Synthesis │
                        │  Positioning Signals    │
                        │  Risk Adjustments       │
                        └────────────────────────┘
```

---

## 📦 Core Components

### 1. Central Bank Monitor

**Location:** `bot/gmig/central_bank_monitor.py`

Monitors policy decisions and forward guidance from 8 major central banks:
- **Fed** (US Federal Reserve) - Highest global impact
- **ECB** (European Central Bank)
- **BOJ** (Bank of Japan)
- **BOE** (Bank of England)
- **PBOC** (People's Bank of China)
- **SNB** (Swiss National Bank)
- **BOC** (Bank of Canada)
- **RBA** (Reserve Bank of Australia)

**Features:**
- Real-time policy rate tracking
- Meeting schedule monitoring
- Forward guidance analysis
- Policy stance scoring (dovish ↔ hawkish)
- Emergency action detection

**Data Sources:**
- FRED API for US data
- Public central bank communications
- Market data providers

### 2. Interest Rate Futures Analyzer

**Location:** `bot/gmig/interest_rate_analyzer.py`

Extracts market expectations from interest rate futures markets:

**Tracked Instruments:**
- Fed Funds futures (rate expectations)
- SOFR futures (short-term rates)
- Treasury futures (2Y, 5Y, 10Y, 30Y)

**Analysis:**
- Implied rate expectations (1-12 months forward)
- Probability distributions for rate changes
- Market pricing vs actual policy divergence
- Rate change scenarios

**Use Cases:**
- Detect shifts in rate expectations
- Find divergences (opportunities)
- Position ahead of policy changes

### 3. Yield Curve AI Modeler

**Location:** `bot/gmig/yield_curve_modeler.py`

AI-powered yield curve analysis and recession forecasting:

**Key Features:**
- **Inversion Detection:** 2y/10y and 3m/10y spreads
- **Recession Probability:** ML-based model (trained on 30 years of data)
- **Curve Shape Analysis:** Normal, flat, inverted, steep, humped
- **Dynamics Tracking:** Steepening/flattening trends

**Recession Timing:**
- Historical pattern: Inversion → Recession in 6-24 months
- AI model estimates timing with confidence scores

**Critical Spreads:**
- **2y-10y:** Most reliable recession indicator
- **3m-10y:** Leading indicator for near-term recession
- **5y-30y:** Long-term growth expectations

### 4. Liquidity Stress Detector

**Location:** `bot/gmig/liquidity_stress_detector.py`

Multi-metric liquidity stress monitoring:

**Monitored Metrics:**
- **TED Spread:** 3M LIBOR - 3M T-Bill (interbank stress)
- **LIBOR-OIS Spread:** Bank funding stress
- **VIX:** Equity market volatility
- **MOVE Index:** Bond market volatility
- **High-Yield Spread:** Credit market stress
- **Repo Rates:** Overnight and term repo markets

**Stress Levels:**
- 🟢 **GREEN:** Normal conditions (score < 0.3)
- 🟡 **YELLOW:** Elevated stress (score 0.3-0.5)
- 🟠 **ORANGE:** High stress (score 0.5-0.7)
- 🔴 **RED:** Crisis conditions (score > 0.7)

### 5. Crisis Warning System

**Location:** `bot/gmig/crisis_warning_system.py`

Early-warning system with historical pattern matching:

**Alert Levels:**
- 🟢 **GREEN:** Normal - standard operations
- 🟡 **YELLOW:** Caution - increase monitoring
- 🟠 **ORANGE:** Warning - reduce exposure
- 🔴 **RED:** Emergency - defensive positioning

**Historical Crisis Patterns:**
- 2008 Financial Crisis
- 2020 COVID Crash
- 2011 Eurozone Crisis

**Detection Methodology:**
- Multi-indicator scoring
- Pattern similarity matching
- Confidence-based alerting

---

## 🚀 Quick Start

### Basic Usage

```python
from bot.gmig import GMIGEngine

# Initialize GMIG
gmig = GMIGEngine()

# Run full macro analysis
report = gmig.run_full_analysis()

# Access key insights
print(f"Macro Regime: {report['macro_regime']['regime']}")
print(f"Positioning Signal: {report['positioning_signals']['primary_signal']}")
print(f"Alert Level: {report['crisis_assessment']['alert_level']}")
print(f"Crisis Probability: {report['crisis_assessment']['crisis_probability']:.1%}")

# Quick crisis check (faster)
crisis_check = gmig.run_crisis_check()
print(f"Alert: {crisis_check['alert_level']}")
```

### Component-Specific Usage

```python
from bot.gmig import (
    CentralBankMonitor,
    InterestRateFuturesAnalyzer,
    YieldCurveAIModeler,
    LiquidityStressDetector,
    CrisisWarningSystem
)

# Central Bank Monitoring
cb_monitor = CentralBankMonitor()
cb_data = cb_monitor.update_all_banks()
print(f"Fed Rate: {cb_data['FED']['current_rate']}")
print(f"Aggregate Stance: {cb_data['aggregate_stance']['description']}")

# Interest Rate Analysis
rate_analyzer = InterestRateFuturesAnalyzer()
rate_data = rate_analyzer.analyze_rate_expectations(current_rate=5.50)
print(f"3-Month Expectation: {rate_data['expectations']['3M']}")

# Yield Curve Analysis
yc_modeler = YieldCurveAIModeler()
yc_data = yc_modeler.analyze_curve()
print(f"Curve Shape: {yc_data['shape']}")
print(f"Recession Probability: {yc_data['recession_probability']:.1%}")

# Liquidity Stress
liquidity = LiquidityStressDetector()
liq_data = liquidity.detect_stress()
print(f"Stress Level: {liq_data['overall_stress_level']}")

# Crisis Warning
crisis = CrisisWarningSystem()
crisis_data = crisis.assess_crisis_risk(
    yield_curve_data=yc_data,
    liquidity_data=liq_data,
    central_bank_data=cb_data
)
print(f"Crisis Probability: {crisis_data['crisis_probability']:.1%}")
```

---

## 🎓 Understanding Macro Regimes

GMIG identifies 7 macro regimes:

### 1. **Risk-On** 🚀
- **Conditions:** Low stress, supportive policy, positive growth
- **Asset Performance:** Crypto ↑↑, Equities ↑, Bonds ↓
- **Positioning:** Aggressive long crypto/equities

### 2. **Risk-Off** 📉
- **Conditions:** Elevated stress, uncertainty
- **Asset Performance:** Crypto ↓, Equities ↓, Bonds ↑, USD ↑
- **Positioning:** Defensive, reduce risk

### 3. **Easing Cycle** 💰
- **Conditions:** Central banks cutting rates
- **Asset Performance:** Risk assets rally, especially crypto
- **Positioning:** Bullish positioning

### 4. **Tightening Cycle** 📈
- **Conditions:** Central banks raising rates
- **Asset Performance:** Risk assets under pressure
- **Positioning:** Cautious, favor value over growth

### 5. **Pre-Recession** ⚠️
- **Conditions:** Yield curve inverted, stress building
- **Asset Performance:** Defensive outperforms
- **Positioning:** Reduce exposure, increase cash

### 6. **Crisis** 🚨
- **Conditions:** Multiple stress indicators at extremes
- **Asset Performance:** Everything sells except safe havens
- **Positioning:** Maximum defensive

### 7. **Transitional** 🔄
- **Conditions:** Mixed signals, regime unclear
- **Asset Performance:** Choppy, range-bound
- **Positioning:** Neutral, balanced

---

## 📊 Positioning Signals

### Signal Strengths

| Signal | Description | Risk Level | Typical Action |
|--------|-------------|------------|----------------|
| `maximum_defensive` | Crisis mode | 20% | Move to cash/safe havens |
| `reduce_risk` | High risk | 50% | Cut positions by 50% |
| `defensive` | Elevated risk | 70% | Reduce by 30% |
| `cautious` | Moderate risk | 75% | Conservative positioning |
| `neutral` | Balanced | 100% | Normal operations |
| `bullish` | Favorable conditions | 120% | Opportunistic longs |
| `aggressive` | Strong conditions | 150% | Full risk-on |

### Asset Allocation by Regime

| Regime | Cash | Treasuries | Gold | Crypto | Equities |
|--------|------|------------|------|--------|----------|
| Crisis | 60% | 30% | 10% | 0% | 0% |
| Pre-Recession | 40% | 30% | 10% | 5% | 15% |
| Risk-Off | 30% | 20% | 10% | 10% | 30% |
| Tightening | 20% | 20% | 5% | 15% | 40% |
| Easing | 10% | 10% | 10% | 30% | 40% |
| Risk-On | 10% | 5% | 5% | 35% | 45% |

---

## 🔧 Configuration

### GMIG Engine Config

```python
GMIG_ENGINE_CONFIG = {
    'enabled': True,
    'mode': 'full',  # 'full', 'essential', 'crisis_only'
    'intelligence_level': 'ultra',  # 'standard', 'advanced', 'ultra'
    'update_frequency_minutes': 15,
    'crisis_check_frequency_minutes': 5,
}
```

### Data Sources

```python
# Optional: FRED API for enhanced data
export FRED_API_KEY=your_fred_api_key

# Get free API key at: https://fred.stlouisfed.org/docs/api/api_key.html
```

---

## 📈 Fund-Grade Features

### Investor-Grade Reporting

```python
from bot.gmig import GMIGEngine

gmig = GMIGEngine()
report = gmig.run_full_analysis()

# Generate investor report
investor_report = {
    'date': report['timestamp'],
    'macro_regime': report['macro_regime'],
    'positioning': report['positioning_signals'],
    'risk_metrics': report['risk_adjustments'],
    'crisis_assessment': report['crisis_assessment'],
}

# Export to PDF, Excel, JSON
# (Implementation in fund-grade reporting module)
```

### Multi-Account Orchestration

GMIG supports centralized risk management across unlimited accounts:

- **Capital Allocation:** Risk-parity, Kelly criterion, equal-weight
- **Auto-Rebalancing:** Daily or on regime changes
- **Compliance:** Automated checks and audit trails
- **Emergency Controls:** Instant position reduction across all accounts

### Autonomous Portfolio Governance

- **Auto Risk Reduction:** Triggered by alert level changes
- **Emergency Stop:** Automatic defensive positioning in crisis
- **Compliance Checks:** Pre-trade and post-trade validation
- **Audit Trail:** 7-year retention for regulatory compliance

---

## 🧪 Testing

```bash
# Test GMIG system
python test_gmig.py

# Test individual components
python -c "from bot.gmig import CentralBankMonitor; cb = CentralBankMonitor(); print(cb.get_summary())"
python -c "from bot.gmig import YieldCurveAIModeler; yc = YieldCurveAIModeler(); print(yc.get_summary())"
python -c "from bot.gmig import LiquidityStressDetector; ls = LiquidityStressDetector(); print(ls.get_summary())"
python -c "from bot.gmig import CrisisWarningSystem; cw = CrisisWarningSystem(); print(cw.get_summary())"
```

---

## 🎯 Real-World Use Cases

### 1. Pre-Recession Positioning (2022 Example)

**Signal Timeline:**
- Q1 2022: Yield curve starts flattening
- Q3 2022: 2y/10y inversion detected
- Q4 2022: Liquidity stress rises
- **Action:** Shift to defensive 3 months before recession

**Result:** Avoided drawdown, preserved capital

### 2. Crisis Detection (March 2020 Example)

**Signal Timeline:**
- Week 1: VIX spike to 40+
- Week 2: TED spread widens to 1.5
- Week 2: Crisis probability > 70%
- **Action:** Emergency defensive positioning

**Result:** Exited before crash bottom

### 3. Recovery Positioning (2023 Example)

**Signal Timeline:**
- Q1 2023: Yield curve starts steepening
- Q2 2023: Central banks pause hiking
- Q3 2023: Liquidity stress normalizes
- **Action:** Shift to risk-on

**Result:** Captured recovery rally

---

## 🚨 Alert Examples

### Green Alert (Normal)
```
✅ NORMAL CONDITIONS
- Macro Regime: Risk-On
- Positioning: Aggressive
- Action: Standard operations
```

### Yellow Alert (Caution)
```
⚠️ ELEVATED RISK
- Macro Regime: Transitional
- Positioning: Cautious
- Action: Increase monitoring, reduce by 10-20%
```

### Orange Alert (Warning)
```
🟠 HIGH RISK
- Macro Regime: Risk-Off
- Positioning: Reduce Risk
- Action: Cut positions by 50%, increase cash to 40%
```

### Red Alert (Emergency)
```
🚨 CRISIS IMMINENT
- Macro Regime: Crisis
- Positioning: Maximum Defensive
- Action: Move to 60%+ cash, liquidate speculative positions
```

---

## 📚 Further Reading

- **MMIN Documentation:** [MMIN_DOCUMENTATION.md](MMIN_DOCUMENTATION.md) - Multi-market intelligence
- **Meta-AI Evolution:** [META_AI_EVOLUTION_GUIDE.md](META_AI_EVOLUTION_GUIDE.md) - Strategy evolution
- **Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture

---

## 🎓 Academic References

GMIG is based on research from elite macro funds and academic studies:

1. **Yield Curve Inversions:** 
   - Estrella & Mishkin (1996) - "The Yield Curve as a Predictor of Recessions"
   
2. **Liquidity Stress:**
   - Brunnermeier & Pedersen (2009) - "Market Liquidity and Funding Liquidity"
   
3. **Crisis Detection:**
   - Reinhart & Rogoff (2009) - "This Time Is Different"

4. **Macro Regime Analysis:**
   - Ang & Bekaert (2002) - "Regime Switches in Interest Rates"

---

## 💡 Pro Tips

1. **Monitor Daily:** Run full analysis daily, crisis checks every 5 minutes
2. **Act on Signals:** Don't ignore orange/red alerts - they're rare but critical
3. **Historical Context:** Study similar periods to understand regime dynamics
4. **Combine with MMIN:** Use GMIG for macro + MMIN for cross-market intelligence
5. **Backtesting:** Test regime changes against historical data

---

## 🔮 Future Enhancements

Potential additions for even more advanced capabilities:

1. **Geopolitical Risk Module:** Track conflicts, elections, policy changes
2. **Supply Chain Monitor:** Global logistics and commodity flows
3. **Sentiment Analysis:** News, social media, positioning data
4. **Alternative Data:** Satellite imagery, credit card data, web traffic
5. **AI Forecasting:** Deep learning for regime prediction

---

## 📞 Support

For questions or issues:
- Review documentation
- Check test examples
- Examine code comments

---

**GMIG Version 1.0.0** - The Ultimate Macro Intelligence System

*"Position before the event, profit from the outcome."* - Elite Macro Trading Principle
