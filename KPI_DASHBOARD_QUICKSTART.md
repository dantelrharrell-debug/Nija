# KPI Dashboard Quick Start Guide

## Overview

The NIJA KPI Dashboard provides **3 key capabilities** for the trading bot:

1. **KPI Dashboards** - Real-time performance metrics
2. **Automated Performance Tracking** - Continuous background monitoring  
3. **Risk Alarms** - Proactive risk alerts

## Installation & Setup

### 1. Dependencies

All dependencies are already in `requirements.txt`:
- numpy
- pandas
- Flask (for API)
- Flask-CORS (for API)

```bash
pip install -r requirements.txt
```

### 2. Quick Start (5 minutes)

```python
from bot.kpi_tracker import get_kpi_tracker
from bot.automated_performance_tracker import get_performance_tracker
from bot.risk_alarm_system import get_risk_alarm_system

# Step 1: Initialize components
kpi_tracker = get_kpi_tracker(initial_capital=10000.0)
performance_tracker = get_performance_tracker()
alarm_system = get_risk_alarm_system()

# Step 2: Configure performance tracker
performance_tracker.set_account_callbacks(
    account_value_fn=lambda: broker.get_account_value(),
    cash_balance_fn=lambda: broker.get_cash_balance(),
    positions_fn=lambda: broker.get_positions()
)

# Step 3: Start automated tracking
performance_tracker.start()

# Done! The system is now monitoring your bot.
```

### 3. Record Trades

```python
# When a trade completes, record it:
kpi_tracker.record_trade(
    symbol='BTC-USD',
    entry_price=50000.0,
    exit_price=51000.0,
    quantity=0.1,
    side='long',
    pnl=100.0,
    entry_time=entry_time,
    exit_time=exit_time,
    fees=1.50
)

# Automatically check for risk alarms
alarm_system.check_all_risks()
```

### 4. View Dashboard

```python
# Get current KPIs
summary = kpi_tracker.get_kpi_summary()

print(f"Win Rate: {summary['trade_stats']['win_rate']:.1f}%")
print(f"Sharpe Ratio: {summary['risk_metrics']['sharpe_ratio']:.2f}")
print(f"Total Return: {summary['returns']['total']:.2f}%")

# Check for active alarms
active_alarms = alarm_system.get_active_alarms()
if active_alarms:
    for alarm in active_alarms:
        print(f"🚨 {alarm.level}: {alarm.message}")
```

## Key Features

### 📊 KPI Tracking

**Metrics Tracked:**
- Win Rate, Profit Factor
- Sharpe Ratio, Sortino Ratio
- Maximum Drawdown
- Daily/Weekly/Monthly Returns
- Average Win/Loss
- Trade Frequency

**Example:**
```python
current = kpi_tracker.get_current_kpis()

print(f"Account: ${current.account_value:,.2f}")
print(f"Return: {current.total_return_pct:.2f}%")
print(f"Win Rate: {current.win_rate_pct:.1f}%")
print(f"Sharpe: {current.sharpe_ratio:.2f}")
```

### 🔄 Automated Tracking

**Features:**
- Background thread updates every 60 seconds (configurable)
- Automatic hourly reports
- State persistence across restarts
- Pause/Resume capability

**Example:**
```python
# Start tracking (runs in background)
tracker.start()

# Check status anytime
status = tracker.get_status()
print(f"Updates: {status['update_count']}")
print(f"Reports: {status['report_count']}")

# Force immediate update/report
tracker.force_update()
tracker.force_report()
```

### 🚨 Risk Alarms

**Alarm Types:**
- Max Drawdown Exceeded
- Daily Loss Limit
- Low Win Rate
- High Position Exposure
- Account Balance Low
- Profit Factor Below 1.0

**Severity Levels:**
- INFO - Informational
- WARNING - Attention needed
- CRITICAL - Action required
- EMERGENCY - Stop trading

**Example:**
```python
# Check all risks
alarm_system.check_all_risks()

# Get active alarms
alarms = alarm_system.get_active_alarms()

for alarm in alarms:
    if alarm.level == 'EMERGENCY':
        # Stop trading!
        bot.stop()
        print(f"⛔ EMERGENCY: {alarm.message}")
        print(f"Action: {alarm.recommended_action}")
```

### 🌐 REST API

**Start API Server:**
```python
from flask import Flask
from bot.kpi_dashboard_api import register_kpi_dashboard_routes

app = Flask(__name__)
register_kpi_dashboard_routes(app)
app.run(host='0.0.0.0', port=5001)
```

**API Endpoints:**
```bash
# Get current KPIs
curl http://localhost:5001/api/kpi/current

# Get last 24 hours of history
curl http://localhost:5001/api/kpi/history?hours=24

# Get active alarms
curl http://localhost:5001/api/alarms/active

# Get complete dashboard
curl http://localhost:5001/api/dashboard/overview
```

## Configuration

### Customize Thresholds

```python
from bot.risk_alarm_system import RiskThresholds, RiskAlarmSystem

# Create custom thresholds
thresholds = RiskThresholds()
thresholds.max_drawdown_pct = 15.0        # Stricter (default: 20%)
thresholds.daily_loss_limit_pct = 3.0    # Stricter (default: 5%)
thresholds.min_win_rate_pct = 60.0       # Higher target (default: 50%)

# Create alarm system with custom thresholds
alarm_system = RiskAlarmSystem(thresholds=thresholds)
```

### Customize Update Intervals

```python
# Update every 30 seconds, report every 30 minutes
tracker = AutomatedPerformanceTracker(
    update_interval=30,
    report_interval=1800
)
```

### Add Custom Notifications

```python
def send_email_alert(alarm):
    """Send email when alarm triggers"""
    if alarm.level in ['CRITICAL', 'EMERGENCY']:
        send_email(
            to="trader@example.com",
            subject=f"🚨 Trading Alert: {alarm.alarm_type}",
            body=f"{alarm.message}\n\nAction: {alarm.recommended_action}"
        )

# Register callback
alarm_system.add_notification_callback(send_email_alert)
```

## Integration Patterns

### Pattern 1: Simple Integration

```python
class MyTradingBot:
    def __init__(self):
        self.kpi = get_kpi_tracker(initial_capital=10000)
        self.alarms = get_risk_alarm_system()
    
    def on_trade_close(self, trade):
        # Record trade
        self.kpi.record_trade(...)
        
        # Check risks
        self.alarms.check_all_risks()
```

### Pattern 2: Full Integration

```python
class AdvancedTradingBot:
    def __init__(self):
        # Initialize all components
        self.kpi = get_kpi_tracker(initial_capital=10000)
        self.tracker = get_performance_tracker()
        self.alarms = get_risk_alarm_system()
        
        # Configure
        self.tracker.set_account_callbacks(
            account_value_fn=self.get_value,
            cash_balance_fn=self.get_cash,
            positions_fn=self.get_positions
        )
        
        # Add alarm handler
        self.alarms.add_notification_callback(self.handle_alarm)
        
        # Start tracking
        self.tracker.start()
    
    def handle_alarm(self, alarm):
        if alarm.level == 'EMERGENCY':
            self.stop_trading()
        elif alarm.level == 'CRITICAL':
            self.reduce_positions()
```

## Data Storage

All data is stored in:
- `./data/kpi/` - KPI snapshots and history
- `./data/performance/` - Performance reports
- `./data/risk_alarms/` - Alarm logs

These directories are automatically created and excluded from git.

## Testing

Run the test suite:
```bash
cd bot
python test_kpi_dashboard.py
```

Run the integration demo:
```bash
cd bot
python kpi_dashboard_integration_example.py
```

## Complete Example

See `bot/kpi_dashboard_integration_example.py` for a complete working example that demonstrates:
- Component initialization
- Trade recording
- Automated tracking
- Risk alarm handling
- Dashboard display

Run it with:
```bash
cd bot
python kpi_dashboard_integration_example.py
```

Expected output:
```
🚀 Starting NIJA KPI Dashboard Demo
✅ KPI Tracker initialized with $10,000.00 initial capital
✅ Automated Performance Tracker started
📈 Simulating trades...
✅ Trade: BTC-USD long - P&L: $95.00
📊 KPI DASHBOARD SUMMARY
Total Return:   3.34%
Win Rate:        100.0%
Sharpe Ratio:    11.14
✅ Demo complete!
```

## Troubleshooting

### Issue: No KPI data available
**Solution:** Update KPIs with account data first:
```python
kpi_tracker.update(
    account_value=10000,
    cash_balance=10000,
    positions=[]
)
```

### Issue: Performance tracker not running
**Solution:** Configure callbacks before starting:
```python
tracker.set_account_callbacks(...)  # Must do this first
tracker.start()
```

### Issue: Alarms not triggering
**Solution:** Check thresholds and manually trigger check:
```python
alarm_system.check_all_risks()
```

## Documentation

Full documentation: `KPI_DASHBOARD.md`

Covers:
- Detailed API reference
- All configuration options
- Advanced usage patterns
- Best practices
- Security considerations

## Support

For issues or questions:
1. Check `KPI_DASHBOARD.md` for detailed documentation
2. Review `bot/kpi_dashboard_integration_example.py` for working example
3. Run tests with `python bot/test_kpi_dashboard.py`
4. Check logs in `./data/` directories

---

**Built for NIJA Trading Bot** - Professional Grade Performance Monitoring
