# Live Profitability Dashboard Specification

## Overview

Real-time dashboard for monitoring NIJA trading profitability and risk metrics.
Focuses on the metrics that matter most: **structural profitability**, not headline PnL.

**Version:** 1.0  
**Date:** February 2026  
**Author:** NIJA Trading Systems

---

## Dashboard Purpose

Monitor trading performance in real-time with emphasis on:
1. **Profitability Structure** - Are wins larger than losses after fees?
2. **Risk Management** - Is exposure controlled and stops working?
3. **Entry Quality** - Are we entering high-quality trades?
4. **Volatility Adaptation** - Is position sizing appropriate for market conditions?

---

## Core Metrics (Always Visible)

### 1. Profitability Structure Panel

**What to Watch:**
- ✅ **Average Win: ≥+2.8%** (net after fees)
- ✅ **Average Loss: ≈-1.5%** (net after fees)
- ✅ **Win Rate: 40-70%** (acceptable range)
- ✅ **Fees: <20% of gross** (efficiency check)
- ✅ **Expectancy: >0%** (positive expected value)

**Display:**
```
┌─────────────────────────────────────────┐
│ PROFITABILITY STRUCTURE                 │
├─────────────────────────────────────────┤
│ Avg Win:     +3.2% ✅                    │
│ Avg Loss:    -1.4% ✅                    │
│ Win Rate:     58.3% ✅                   │
│ R/R Ratio:    2.3:1 ✅                   │
│ Expectancy:  +0.87% ✅                   │
│ Fee Impact:   14.2% ✅                   │
└─────────────────────────────────────────┘
```

**Alert Triggers:**
- 🚨 Expectancy drops below 0%
- ⚠️ Avg win drops below +2.0%
- ⚠️ Avg loss exceeds -2.5%
- ⚠️ Fees exceed 25% of gross

---

### 2. Current Positions Panel

**Metrics:**
- Total exposure (% of capital)
- Volatility-weighted exposure
- Active positions count
- Unrealized PnL
- Average position volatility (ATR%)
- Largest position size
- Trailing stop levels

**Display:**
```
┌─────────────────────────────────────────┐
│ ACTIVE POSITIONS                        │
├─────────────────────────────────────────┤
│ Total Exposure:    42.5% / 60% max      │
│ Vol-Weighted:      48.2%                │
│ Positions:         3 open               │
│ Unrealized PnL:   +$42.15               │
│ Avg Volatility:    2.3% ATR             │
│                                         │
│ BTC-USD:  +1.2%  (12% capital, 2.1% ATR)│
│ ETH-USD:  +0.8%  (15% capital, 2.5% ATR)│
│ SOL-USD:  -0.3%  (15.5% capital, 2.9% ATR)│
└─────────────────────────────────────────┘
```

**Alert Triggers:**
- 🚨 Total exposure exceeds 70%
- 🚨 Vol-weighted exposure exceeds 80%
- ⚠️ Any position down more than -3%
- ⚠️ Average volatility exceeds 4%

---

### 3. Entry Quality Panel

**Metrics:**
- Recent entry scores (0-100)
- Entry quality distribution
- Pass/fail rate
- Average score for winning vs losing trades

**Display:**
```
┌─────────────────────────────────────────┐
│ ENTRY QUALITY (Last 10 Entries)        │
├─────────────────────────────────────────┤
│ Average Score:     72.3 / 100           │
│ Pass Rate:         80% (8/10)           │
│                                         │
│ Quality Distribution:                   │
│ EXCELLENT (85+):  ██░░░░░░░░ 20%        │
│ VERY_GOOD (75+):  ████░░░░░░ 40%        │
│ GOOD (65+):       ██░░░░░░░░ 20%        │
│ ACCEPTABLE (55+): ██░░░░░░░░ 20%        │
│ MARGINAL (45+):   ░░░░░░░░░░  0%        │
│ POOR (<45):       ░░░░░░░░░░  0%        │
│                                         │
│ Last Entry: BTC-USD                     │
│ Score: 78/100 (VERY_GOOD) ✅            │
│ Signal:25 Trend:22 Vol:18 Volume:13    │
└─────────────────────────────────────────┘
```

**Alert Triggers:**
- ⚠️ Entry score below 60
- 🚨 Pass rate drops below 50%
- ⚠️ Average score drops below 65

---

### 4. Risk Exposure Panel

**Metrics:**
- Portfolio heat (total risk exposure)
- Max drawdown (current)
- Dynamic stop levels
- Stop expansion count
- Risk concentration

**Display:**
```
┌─────────────────────────────────────────┐
│ RISK EXPOSURE                           │
├─────────────────────────────────────────┤
│ Portfolio Heat:    3.2% of capital      │
│ Max Drawdown:     -2.1% (within limits) │
│                                         │
│ Dynamic Stops:                          │
│ BTC-USD: 2.5x ATR (EXPANDED - Strong trend)│
│ ETH-USD: 2.0x ATR (INITIAL)             │
│ SOL-USD: 3.0x ATR (EXPANDED - Very strong)│
│                                         │
│ Risk Concentration:                     │
│ Crypto: 100% (3 positions)              │
└─────────────────────────────────────────┘
```

**Alert Triggers:**
- 🚨 Portfolio heat exceeds 8%
- 🚨 Max drawdown exceeds -10%
- ⚠️ Risk concentration in single asset >30%

---

### 5. Volatility Adaptation Panel

**Metrics:**
- Current market volatility regime
- Position size adjustments
- Volatility trends
- ATR percentiles

**Display:**
```
┌─────────────────────────────────────────┐
│ VOLATILITY ADAPTATION                   │
├─────────────────────────────────────────┤
│ Market Regime:     NORMAL               │
│ Avg ATR:          2.4% (25th percentile)│
│                                         │
│ Position Sizing:                        │
│ Base:             5% per position       │
│ Vol Adjusted:     5.5% (low vol boost)  │
│                                         │
│ Recent Adjustments:                     │
│ BTC: 5% → 6.2% (low vol)                │
│ ETH: 5% → 4.8% (slightly high vol)      │
│ SOL: 5% → 4.5% (higher vol)             │
└─────────────────────────────────────────┘
```

**Alert Triggers:**
- 🚨 Volatility regime shifts to EXTREME
- ⚠️ Volatility regime shifts to HIGH
- ℹ️ Volatility regime shifts to LOW

---

## Secondary Metrics (Available on Demand)

### Performance Timeline
- 24-hour rolling PnL
- Hourly breakdown
- Best/worst trades
- Daily summary

### Trade History
- Last 20 completed trades
- Win/loss sequence
- Hold times
- Exit reasons

### Fee Analysis
- Total fees paid (24h, 7d, 30d)
- Fee percentage by exchange
- Fee efficiency score
- Recommendations for fee optimization

### System Health
- API connection status
- Order execution latency
- Error rates
- Last update timestamp

---

## Dashboard Layout

### Desktop/Web Layout

```
┌─────────────────────────────────────────────────────────┐
│ NIJA Live Profitability Dashboard    [Last Update: 2s] │
├──────────────────────┬──────────────────────────────────┤
│ PROFITABILITY        │ ACTIVE POSITIONS                 │
│ STRUCTURE            │                                  │
│ (Core Metrics)       │ (Position Details)               │
│                      │                                  │
├──────────────────────┼──────────────────────────────────┤
│ ENTRY QUALITY        │ RISK EXPOSURE                    │
│                      │                                  │
│ (Quality Scores)     │ (Risk Metrics)                   │
│                      │                                  │
├──────────────────────┴──────────────────────────────────┤
│ VOLATILITY ADAPTATION                                   │
│                                                         │
│ (Vol Regime & Position Sizing)                         │
└─────────────────────────────────────────────────────────┘
```

### Mobile Layout

```
┌────────────────────┐
│ NIJA Dashboard     │
├────────────────────┤
│ [Tabs]             │
│ Structure | Positions | Quality | Risk | Vol
├────────────────────┤
│                    │
│  Active Tab        │
│  Content           │
│                    │
└────────────────────┘
```

---

## Technical Implementation

### API Endpoints

#### GET /api/dashboard/profitability
Returns profitability structure metrics
```json
{
  "avg_win_pct": 3.2,
  "avg_loss_pct": -1.4,
  "win_rate": 58.3,
  "rr_ratio": 2.3,
  "expectancy": 0.87,
  "fee_percentage": 14.2,
  "status": "healthy"
}
```

#### GET /api/dashboard/positions
Returns active positions with risk metrics
```json
{
  "total_exposure_pct": 42.5,
  "vol_weighted_exposure": 48.2,
  "positions": [
    {
      "symbol": "BTC-USD",
      "pnl_pct": 1.2,
      "size_pct": 12,
      "atr_pct": 2.1,
      "stop_multiplier": 2.5,
      "trend_strength": "STRONG"
    }
  ]
}
```

#### GET /api/dashboard/entry-quality
Returns entry quality metrics
```json
{
  "average_score": 72.3,
  "pass_rate": 80.0,
  "distribution": {
    "EXCELLENT": 20,
    "VERY_GOOD": 40,
    "GOOD": 20,
    "ACCEPTABLE": 20
  },
  "last_entry": {
    "symbol": "BTC-USD",
    "score": 78,
    "rating": "VERY_GOOD"
  }
}
```

#### GET /api/dashboard/risk
Returns risk exposure metrics
```json
{
  "portfolio_heat": 3.2,
  "max_drawdown": -2.1,
  "dynamic_stops": [
    {
      "symbol": "BTC-USD",
      "multiplier": 2.5,
      "status": "EXPANDED"
    }
  ]
}
```

#### GET /api/dashboard/volatility
Returns volatility adaptation metrics
```json
{
  "market_regime": "NORMAL",
  "avg_atr_pct": 2.4,
  "base_position_pct": 5.0,
  "vol_adjusted_pct": 5.5
}
```

### WebSocket Updates (Real-time)

Subscribe to real-time updates:
- Position changes
- New trades
- Entry quality scores
- Risk alerts

```javascript
ws://api.nija.bot/ws/dashboard
```

### Update Frequency

- **Profitability Structure:** Every 10 seconds
- **Active Positions:** Every 2 seconds
- **Entry Quality:** On new entry
- **Risk Exposure:** Every 5 seconds
- **Volatility Adaptation:** Every 30 seconds

---

## Alert System

### Critical Alerts (Immediate Notification)
- 🚨 Negative expectancy
- 🚨 Exposure exceeds limits
- 🚨 Drawdown exceeds threshold
- 🚨 API connection lost

### Warning Alerts (Email/Push)
- ⚠️ Fee percentage too high
- ⚠️ Entry quality declining
- ⚠️ Volatility regime change
- ⚠️ Win rate dropping

### Info Alerts (Dashboard Only)
- ℹ️ New position opened
- ℹ️ Position closed
- ℹ️ Stop expanded
- ℹ️ Volatility adjustment made

---

## Integration with Existing Systems

### Data Sources
- `entry_quality_audit.py` - Entry scoring
- `volatility_adaptive_sizing.py` - Vol metrics
- `dynamic_stop_manager.py` - Stop data
- `performance_dashboard.py` - Trade history
- `risk_manager.py` - Risk calculations

### Dashboard Implementation Files
- `bot/live_dashboard_api.py` - API endpoints
- `frontend/dashboard/` - UI components
- `bot/dashboard_aggregator.py` - Data aggregation

---

## First 48 Hour Monitoring Checklist

### Hour 0-6 (Initial Deployment)
- [ ] All API endpoints responding
- [ ] WebSocket connections stable
- [ ] First trade entry quality >60
- [ ] Position sizing within limits

### Hour 6-24 (Early Performance)
- [ ] At least 3 completed trades
- [ ] No cascading drawdowns
- [ ] Fee percentage trending <20%
- [ ] Entry quality pass rate >60%

### Hour 24-48 (Confirmation)
- [ ] Avg win ≥ +2.5%
- [ ] Avg loss ≤ -2.0%
- [ ] Expectancy positive
- [ ] Win rate 40-70%
- [ ] Structure validates: NIJA IS FIXED ✅

---

## Maintenance & Updates

### Daily
- Review alert log
- Check fee efficiency
- Validate entry quality

### Weekly
- Profitability structure audit
- Risk exposure analysis
- Performance comparison vs baseline

### Monthly
- Full system audit
- Parameter optimization review
- Dashboard UX improvements

---

## Security & Access

### Access Levels

**Level 1 (Public):**
- Performance timeline
- Trade count
- Win rate

**Level 2 (Authenticated):**
- Full profitability structure
- Active positions
- Entry quality scores

**Level 3 (Admin):**
- Individual trade details
- API credentials status
- System health diagnostics

### Authentication
- JWT tokens
- Rate limiting: 60 requests/minute
- API keys for programmatic access

---

## Future Enhancements

### Phase 2
- Mobile app integration
- Push notifications
- Voice alerts for critical events
- Historical comparison charts

### Phase 3
- Multi-strategy comparison
- Portfolio optimization suggestions
- Predictive analytics
- Machine learning trade quality predictions

---

## Success Metrics

Dashboard is successful when:
1. ✅ Users can instantly see if NIJA is profitable
2. ✅ Alerts catch problems before major losses
3. ✅ Entry quality prevents bad trades
4. ✅ Risk exposure stays controlled
5. ✅ Expectancy remains positive

**Bottom Line:** If structure is healthy, NIJA is officially fixed. 🎯

---

**Document Version:** 1.0  
**Last Updated:** February 2026  
**Status:** Specification Complete - Ready for Implementation
