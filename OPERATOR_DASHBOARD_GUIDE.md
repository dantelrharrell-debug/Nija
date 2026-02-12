# 🎯 NIJA Operator Dashboard & Readiness Cheat Sheet

**Version:** 7.2.0  
**Purpose:** Single-page mission control view for NIJA trading bot operations  
**Target Audience:** Bot operators, system administrators, technical support

---

## 📋 Overview

The **NIJA Operator Dashboard** is a comprehensive single-page reference that consolidates:

- ✅ **Active Guardrails** - All safety limits and circuit breakers
- ✅ **Performance Metrics** - 8 key command center metrics
- ✅ **Scaling Logic** - Tier progression and greenlight criteria
- ✅ **Frozen Limits** - Unbypasable position caps and thresholds
- ✅ **Emergency Procedures** - Critical response protocols
- ✅ **Monitoring Commands** - Real-time status and diagnostics
- ✅ **Troubleshooting** - Common issues and resolutions

This dashboard serves as your **mission control** for operating NIJA safely and effectively.

---

## 🚀 Quick Start

### Option 1: Open in Browser (Recommended)

```bash
# Open the HTML dashboard directly
open NIJA_OPERATOR_DASHBOARD.html

# Or on Linux
xdg-open NIJA_OPERATOR_DASHBOARD.html

# Or start a local server
python -m http.server 8000
# Then navigate to: http://localhost:8000/NIJA_OPERATOR_DASHBOARD.html
```

### Option 2: Print to PDF

The dashboard is optimized for printing to PDF for offline reference:

1. Open `NIJA_OPERATOR_DASHBOARD.html` in your browser
2. Press `Ctrl+P` (or `Cmd+P` on Mac)
3. Select "Save as PDF"
4. Save as `NIJA_Operator_Dashboard.pdf`

### Option 3: Keep in Browser Tab

Many operators keep the dashboard open in a pinned browser tab for instant reference.

---

## 📊 Dashboard Sections

### 🚨 Emergency Kill Switch (Priority #1)

**Location:** Top of dashboard  
**Purpose:** Fastest methods to halt all trading immediately

**Three activation methods:**
1. **CLI** (<5 seconds) - Fastest
2. **File System** (<10 seconds) - Simple
3. **API** (<10 seconds) - Automated

**When to use:**
- Uncontrolled losses
- API errors or connectivity issues
- Suspicious trading activity
- System malfunction
- Any emergency requiring immediate halt

---

### 🔒 Position Limits (Frozen)

**Unbypasable hard limits:**

| Limit Type | Value | Bypasable? |
|------------|-------|------------|
| Max Positions | 7-8 | ❌ NO |
| Absolute % Cap | 15% | ❌ NO |
| Absolute $ Cap | $10,000 | ❌ NO |

These limits are **hardcoded** and cannot be overridden by any user, configuration, or code path.

---

### 📊 Tier Configuration

Six trading tiers from STARTER ($50) to BALLER ($25K+), each with:
- Capital range
- Risk per trade percentage
- Maximum concurrent positions
- Trade size limits

**Key threshold:** $100 minimum recommended for fee efficiency

---

### ⚡ Circuit Breakers

Automatic safety systems that trigger based on:
- Order stuck time (5 min warning, 15 min auto-kill)
- Adoption rate (80% threshold)
- Platform exposure (30% warning, 45% max)
- Daily loss limits (tier-specific)
- Position cap (hard stop at 7-8)
- Account drawdown (8% triggers 24h halt)

---

### 📈 Performance Metrics

**8 Key Command Center Metrics:**
1. Equity Curve - Portfolio value and 24h change
2. Risk Heat - Risk score (0-100) and drawdown %
3. Trade Quality - Win rate and profit factor
4. Signal Accuracy - Success rate and false positives
5. Slippage - Basis points and USD impact
6. Fee Impact - Total fees as % of profit
7. Strategy Efficiency - Trades per day and capital utilization
8. Capital Growth Velocity - Annualized growth rate

**Access:** `python bot/dashboard_server.py` → http://localhost:5001/command-center

---

### 🔍 Market Quality Filters

Prevents trading in unfavorable conditions:
- **ADX < 20** - Weak trend (choppy market)
- **Volume < 50%** - Low liquidity
- **First 30 seconds** - Candle volatility
- **Spread > 10 BPS** - High slippage risk
- **Low volatility** - Insufficient movement
- **Flash crash** - 15% drop in 5 min

---

### 📊 Scaling Logic (Greenlight)

**Unlock Tier 2 Requirements (ALL must be met):**
- Net Profit ≥ $50
- ROI ≥ 5%
- Win Rate ≥ 45%
- Max Drawdown ≤ 15%
- Trade Count ≥ 50
- Time Period ≥ 24 hours
- Kill Switches = 0 triggers
- Daily Limits = 0 hits
- Position Rejects ≤ 5%

**Generate report:** `python generate_greenlight_report.py --user <username>`

---

### ⚙️ Status & Diagnostic Commands

Quick commands for:
- Overall profit status
- Capital capacity calculations
- Kraken diagnostics
- Profitability analysis
- Analytics reports
- Paper trading status
- User status summaries

All commands are copy-paste ready from the dashboard.

---

### 🌐 Real-Time API Endpoints

Six critical endpoints on ports 5000 and 5001:
- `/api/last-trade` - Latest trade evaluation
- `/api/health` - System health check
- `/api/dry-run-status` - Trading mode
- `/api/emergency/kill-switch/status` - Emergency status
- `/api/performance/status` - Performance metrics
- `/api/graduation/status` - Tier progression

---

### 🚫 Trade Veto Reasons

10 common reasons trades are blocked:
- Position cap reached
- Insufficient balance
- Daily loss limit
- Kill switch active
- Market filters failed
- Risk limits exceeded
- LIVE_CAPITAL_VERIFIED not set
- Revenge trading detected
- Excessive frequency
- Overconcentration

---

### 📥 Entry Reasons & 📤 Exit Reasons

**11 Entry Types:**
- RSI oversold signals (9, 14, dual)
- RSI divergence
- TradingView signals
- Market readiness
- Strong momentum
- Manual/heartbeat trades

**19 Exit Types:**
- Profit targets (partial and full)
- Stop losses (hard, time-based, aggressive)
- Risk management (daily loss, position limit, kill switch)
- Market conditions (RSI, dust, zombie, adoption)

---

### ⚠️ Risk Profiles

Three exchange-specific profiles:
- **Conservative** - 1x leverage, 5% drawdown (spot trading)
- **Moderate** - 2-3x leverage, 10% drawdown (low leverage futures)
- **Aggressive** - 5x leverage, 15% drawdown (high leverage, advanced)

---

### 🔧 Critical Environment Variables

Six key environment variables:
- `KRAKEN_PLATFORM_API_KEY` - **Required**
- `KRAKEN_PLATFORM_API_SECRET` - **Required**
- `LIVE_CAPITAL_VERIFIED` - **Required** for live trading
- `DRY_RUN_MODE` - Optional (paper trading)
- `HEARTBEAT_TRADE` - Optional (test execution)
- `LAST_TRADE_API_PORT` - Port configuration (default: 5001)

---

### ✅ Safety Test Suite

Six critical tests to run before deployment:
```bash
python test_operational_safety.py      # Must show 7/7 pass
python test_critical_safety.py
python test_health_check_system.py
python test_position_cap_enforcement.py
python test_risk_freeze.py
python test_tier_and_risk_changes.py
```

**Expected:** All tests PASS ✅, no exceptions, all guardrails functioning

---

### ⚡ Rapid Fire Commands

18 copy-paste commands for:
- Quick health checks (`curl` one-liners)
- Kill switch status
- Real-time monitoring (`watch` commands)
- Git status
- Log viewing
- Safety test execution
- Bot start/restart
- API testing

---

### 🐛 Troubleshooting Checklist

Four common scenarios with checklists:
1. **Bot Won't Start** - Check API keys, permissions, logs, connectivity
2. **No Trades Executing** - Check veto logs, capital verification, balance
3. **Heartbeat Trade Fails** - Check balance, permissions, API errors
4. **API Not Responding** - Check port, server status, firewall

---

### 🚨 Emergency Protocol

**5-Step Memorized Response:**
1. **Activate Kill Switch** - Immediately
2. **Review Logs** - `tail -f logs/nija.log`
3. **Check Positions** - Via broker UI
4. **Follow Procedures** - See `OPERATIONAL_SAFETY_PROCEDURES.md`
5. **Verify & Deactivate** - Only after issue resolved

**Golden Rule:** In ANY emergency, activate kill switch FIRST, investigate SECOND!

---

### 📚 Key Documentation

Four categories of documentation:
1. **Core Guides** - README, Quick Reference, Getting Started
2. **Safety & Operations** - Operational Safety, Kill Switch, Hard Controls
3. **Trading & Strategy** - APEX V7.1, Broker Integration, TradingView
4. **Analytics & Monitoring** - Analytics, Command Center, KPI Dashboard

---

## 🎨 Visual Design

The dashboard uses color coding for quick visual scanning:

| Color | Section Type | Use Case |
|-------|--------------|----------|
| 🔴 Red | Emergency | Kill switch, critical alerts |
| 🟠 Orange | Warning | Position limits, vetoes |
| 🟢 Green | Success | Performance, metrics |
| 🔵 Blue | Information | Status, API endpoints |
| 🟣 Purple | Filters | Market quality, exit reasons |

---

## 💡 Best Practices

### For Daily Operations
1. **Keep dashboard open** in a pinned browser tab
2. **Review metrics** at start of each trading session
3. **Check circuit breakers** after any unusual market activity
4. **Monitor API endpoints** for real-time status

### For Emergency Situations
1. **Know kill switch commands** by heart
2. **Have dashboard accessible** on mobile device
3. **Follow 5-step protocol** without deviation
4. **Document all incidents** in logs

### For System Maintenance
1. **Run safety tests** before any deployment
2. **Verify environment variables** after configuration changes
3. **Test API endpoints** after restarts
4. **Review recent logs** for warnings

---

## 📱 Mobile Access

The dashboard is responsive and works on mobile devices:
1. Save dashboard URL to home screen
2. Access from phone during emergencies
3. Use rapid fire commands via SSH client
4. Monitor API endpoints via mobile browser

---

## 🔄 Updates

The dashboard is synchronized with:
- **Bot Version:** 7.2.0
- **Documentation:** February 2026
- **Configuration Files:** Current repository state

**To update:**
1. Review changes in configuration files
2. Update values in dashboard HTML
3. Test all sections for accuracy
4. Document changes in git commit

---

## 🤝 Contributing

To improve the dashboard:
1. Identify missing guardrails or metrics
2. Update HTML file with new information
3. Test visual layout and formatting
4. Update this README with new sections
5. Submit pull request with clear description

---

## 📞 Support

For dashboard-related questions:
- **Emergency:** Follow kill switch protocol
- **Technical Issues:** Review troubleshooting section
- **Documentation:** See key documentation list
- **Updates:** Check repository for latest version

---

## ✅ Validation Checklist

Before using dashboard in production:
- [ ] All guardrail values are accurate
- [ ] Performance metrics match code
- [ ] Tier configuration is current
- [ ] Emergency commands work
- [ ] API endpoints are accessible
- [ ] Environment variables are documented
- [ ] Safety tests pass
- [ ] Troubleshooting steps are valid

---

**Last Updated:** February 12, 2026  
**Maintained By:** NIJA Trading Systems  
**Version:** 7.2.0  

---

## 🔗 Related Files

- `NIJA_OPERATOR_DASHBOARD.html` - Main dashboard (this documentation)
- `NIJA_OPERATOR_QUICK_REFERENCE.html` - Previous quick reference card
- `NIJA_OPERATOR_QUICK_REFERENCE.md` - Markdown quick reference
- `OPERATORS_DASHBOARD_GUIDE.md` - User status dashboard guide
- `OPERATIONAL_SAFETY_PROCEDURES.md` - Detailed safety protocols
- `HARD_CONTROLS.md` - Hard control specifications
- `INSTITUTIONAL_GUARDRAILS.md` - Institutional safety guardrails

---

**Remember:** This dashboard is your first line of defense in bot operations. Keep it accessible, review it regularly, and memorize the emergency protocol!
