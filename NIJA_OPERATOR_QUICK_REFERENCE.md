# 🎯 NIJA Operator Quick Reference Card

**Version 7.2.0** | Emergency Response & Monitoring Guide | Target Response Time: <30 seconds

---

## 🚨 EMERGENCY KILL SWITCH (Priority #1)

**When to Use:** Uncontrolled losses, API errors, suspicious activity, system malfunction

### Fastest Activation Methods
```bash
# CLI (< 5 seconds) - FASTEST
python emergency_kill_switch.py activate emergency

# File System (< 10 seconds)
touch EMERGENCY_STOP

# API (< 10 seconds)
curl -X POST http://localhost:5000/api/emergency/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency halt"}'
```

### Check Status
```bash
python emergency_kill_switch.py status
curl http://localhost:5000/api/emergency/kill-switch/status
```

---

## 📊 STATUS COMMANDS

### Account & Balance Status
```bash
# Overall profit status (Kraken + Coinbase)
python check_profit_status.py
python check_profit_status.py --detailed

# Calculate capital capacity
python calculate_capital_capacity.py

# All accounts capital
python calculate_all_accounts_capital.py

# Safe trade size calculator
python calculate_safe_trade_size.py
```

### Trading System Status
```bash
# Diagnose Kraken trading issues
python diagnose_kraken_trading.py

# Diagnose general trading logic
python diagnose_trading_logic.py

# Check profitability analysis
python analyze_profitability.py

# Heartbeat trade verification
# Set HEARTBEAT_TRADE=true in environment, then check logs for:
# 💓 HEARTBEAT TRADE VERIFICATION: ✅ SUCCESS
```

### Analytics & Reports
```bash
# Generate analytics report
python generate_analytics_report.py
python generate_analytics_report.py --detailed
python generate_analytics_report.py --export-csv

# Paper trading analytics
python paper_trading_manager.py --report
python paper_trading_manager.py --analyze
python paper_trading_manager.py --kill-losers
python paper_trading_manager.py --check-ready

# Generate greenlight report
python generate_greenlight_report.py

# Profitability audit report
python profitability_audit_report.py
```

---

## 🔔 ALERTS & MONITORING

### Critical Alert Thresholds

| Alert Type | Threshold | Auto Kill-Switch |
|------------|-----------|------------------|
| Order Stuck | 5 minutes | Optional (15 min) |
| Adoption Rate | 80% | Configurable |
| Platform Exposure | 30% | Configurable (45%) |
| Daily Loss Limit | Per tier config | Yes |
| Position Limit | 7 positions | Blocked |

### Monitor Alerts (Programmatic)
```python
from bot.monitoring_system import monitoring

# Check stuck orders
stuck = monitoring.check_stuck_orders()

# Check adoption guardrail
monitoring.check_adoption_guardrail(active_users=50, total_users=100)

# Check platform exposure
monitoring.check_platform_exposure(
    platform_balances={'Coinbase': 1000.0},
    total_balance=1500.0
)
```

### Run Safety Tests
```bash
python test_operational_safety.py       # Expected: 7/7 tests pass
python test_critical_safety.py
python test_health_check_system.py
```

---

## 📸 SNAPSHOTS & METRICS

### Performance Snapshots
```python
from bot.performance_metrics import get_metrics
from bot.command_center_metrics import get_command_center

# Get performance snapshot
metrics = get_metrics()
snapshot = metrics.get_snapshot()

# Command Center snapshot (8 metrics)
command_center = get_command_center()
cc_snapshot = command_center.get_snapshot()
```

### API Endpoints for Real-Time Data
```bash
# Last evaluated trade
GET http://localhost:5001/api/last-trade

# Health check
GET http://localhost:5001/api/health

# Dry-run status
GET http://localhost:5001/api/dry-run-status

# Kill switch status
GET http://localhost:5000/api/emergency/kill-switch/status

# Performance status
GET http://localhost:5000/api/performance/status

# Graduation status
GET http://localhost:5000/api/graduation/status
```

### Command Center Metrics (Dashboard)
Start the dashboard:
```bash
python bot/dashboard_server.py
# Access: http://localhost:5001/command-center
```

**8 Key Metrics:**
1. ✅ Equity Curve (portfolio value, 24h change)
2. ✅ Risk Heat (0-100 score, drawdown %)
3. ✅ Trade Quality Score (0-100, win rate, profit factor)
4. ✅ Signal Accuracy (success rate, false positives)
5. ✅ Slippage (bps, USD impact)
6. ✅ Fee Impact (total fees, % of profit)
7. ✅ Strategy Efficiency (trades/day, capital utilization)
8. ✅ Capital Growth Velocity (annualized rate)

---

## 🔍 MARKET FILTERS

### Market Quality Filters
```python
from bot.market_filters import (
    detect_choppy_market,
    check_minimum_volume,
    filter_recent_candle_start,
    check_spread_and_slippage
)

# Detect choppy/ranging markets
chop_result = detect_choppy_market(df, adx_threshold=20)
# Returns: {'is_choppy': bool, 'reason': str, 'adx_value': float}

# Check volume sufficiency
vol_result = check_minimum_volume(df, min_volume_multiplier=0.5)
# Returns: {'volume_sufficient': bool, 'reason': str}

# Avoid trading first seconds of candle
early_candle = filter_recent_candle_start(df, avoid_seconds=30)
# Returns: {'is_too_early': bool, 'seconds_into_candle': int}

# Check spread/slippage
spread_result = check_spread_and_slippage(df, max_spread_bps=10)
# Returns: {'spread_ok': bool, 'spread_bps': float}
```

### Filter Thresholds (Default)
- **ADX Threshold:** < 20 (weak trend, choppy market)
- **Min Volume:** 50% of 20-period average
- **Avoid First:** 30 seconds of new candle
- **Max Spread:** 10 basis points
- **Low Volatility:** ATR < 0.1% of price

---

## 🎯 OPERATIONAL QUICK ACTIONS

### Start/Stop Trading
```bash
# Start trading bot
./start.sh
python bot.py

# Restart with specific script
./restart_nija.sh
python bot/live_bot_script.py
```

### Environment Configuration
```bash
# Required variables for live trading
KRAKEN_PLATFORM_API_KEY=<key>
KRAKEN_PLATFORM_API_SECRET=<secret>
LIVE_CAPITAL_VERIFIED=true
HEARTBEAT_TRADE=false
DRY_RUN_MODE=false

# API server port
LAST_TRADE_API_PORT=5001

# Test mode (App Store review)
DRY_RUN_MODE=true
```

### Trade Veto Reasons (Why Trades Get Blocked)
- ❌ Position cap reached (7/7 positions)
- ❌ Insufficient balance (< minimum required)
- ❌ Daily loss limit reached
- ❌ Kill switch active
- ❌ Market quality filters failed
- ❌ Risk limits exceeded
- ❌ LIVE_CAPITAL_VERIFIED not set

---

## 📈 ANALYTICS TRACKING

### Entry Reasons (11 Types)
- `rsi_9_oversold` - RSI_9 < 30
- `rsi_14_oversold` - RSI_14 < 30
- `dual_rsi_oversold` - Both RSI < 30
- `rsi_divergence` - Divergence detected
- `tradingview_buy_signal` / `tradingview_sell_signal`
- `market_readiness_passed` - Quality gate passed
- `strong_momentum`
- `manual_entry` / `heartbeat_trade`
- `unknown` - Fallback

### Exit Reasons (19 Types)
**Profit Targets:**
- `profit_target_1/2/3` - Partial exits (25% each)
- `full_profit_target` - 100% exit
- `trailing_stop_hit` - Trailing stop

**Stop Losses:**
- `stop_loss_hit` - Hard stop
- `time_based_stop` - Max hold time (24h+)
- `losing_trade_exit` - Aggressive cut (15min)

**Risk Management:**
- `daily_loss_limit`, `position_limit_enforcement`
- `kill_switch`, `liquidate_all`

**Other:**
- `rsi_overbought`, `rsi_oversold_exit`
- `dust_position`, `zombie_position`, `adoption_exit`
- `manual_exit`, `unknown`

---

## 🧠 ADVANCED FEATURES

### NAMIE (Market Intelligence Engine)
```python
from bot.namie_integration import quick_namie_check

# One-line market intelligence check
should_trade, reason, signal = quick_namie_check(df, indicators, "BTC-USD")

# Features:
# - Auto-switches strategies based on market regime
# - Prevents chop losses through sideways market filtering
# - Boosts win rate (+5-10%) via regime-optimized entry
# - Increases R:R ratio (+20-30%) through adaptive profit targets
```

### Paper Trading Graduation
```bash
# 3-Phase optimization process
python demo_paper_analytics.py --trades 150    # 1. Collect data
python paper_trading_manager.py --kill-losers  # 2. Kill losers
python paper_trading_manager.py --check-ready  # 3. Validate profit-ready
```

---

## 📖 KEY DOCUMENTATION FILES

| Document | Purpose |
|----------|---------|
| `README.md` | Main project overview |
| `QUICK_REFERENCE.md` | Railway deployment & features |
| `EMERGENCY_KILL_SWITCH_QUICK_REF.md` | Emergency procedures |
| `ANALYTICS_QUICK_REFERENCE.md` | Analytics commands |
| `OPERATIONAL_SAFETY_PROCEDURES.md` | Safety protocols |
| `COMMAND_CENTER_README.md` | Dashboard metrics |
| `BROKER_INTEGRATION_GUIDE.md` | Coinbase/Kraken setup |
| `TRADINGVIEW_SETUP.md` | Webhook configuration |

---

## 🐛 TROUBLESHOOTING CHECKLIST

### Bot Won't Start
- [ ] Check `KRAKEN_PLATFORM_API_KEY` and `KRAKEN_PLATFORM_API_SECRET` are set
- [ ] Verify API permissions: "Create & Modify Orders" enabled
- [ ] Check logs for specific error messages

### No Trades Executing
- [ ] Look for `🚫 TRADE VETO` messages in logs
- [ ] Check veto reasons (balance, position cap, kill switch)
- [ ] Verify `LIVE_CAPITAL_VERIFIED=true` is set
- [ ] Ensure account has minimum balance ($25+)

### Heartbeat Trade Fails
- [ ] Account has at least $25 balance
- [ ] API key has order creation permission
- [ ] Check logs for specific API error

### API Not Responding
- [ ] Port 5001 is exposed in deployment
- [ ] API server started (check logs for "API server started")
- [ ] Firewall allows port 5001

---

## ⚡ RAPID FIRE COMMANDS

```bash
# Quick system health check
curl http://localhost:5001/api/health | jq
curl http://localhost:5000/api/emergency/kill-switch/status | jq

# Monitor last trade in real-time
watch -n 5 'curl -s http://localhost:5001/api/last-trade | jq .data'

# Check git status of bot
git --no-pager status
git --no-pager diff

# Test API locally
python bot/last_trade_api.py

# View recent logs
tail -f logs/nija.log

# Run all safety tests
python test_operational_safety.py && \
python test_critical_safety.py && \
python test_health_check_system.py
```

---

**🚨 REMEMBER:** In any emergency, activate kill switch FIRST, investigate SECOND!

**📞 Emergency Protocol:**
1. Activate kill switch immediately
2. Review logs: `tail -f logs/nija.log`
3. Check positions via broker UI
4. Follow procedures in `OPERATIONAL_SAFETY_PROCEDURES.md`
5. Only deactivate after issue is resolved and verified

---

*Last Updated: February 2026 | Version 7.2.0*
