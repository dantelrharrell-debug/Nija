# NIJA KPI Dashboard, Performance Tracking & Risk Alarms

Complete guide for the NIJA trading bot's KPI monitoring, automated performance tracking, and risk alarm systems.

## Table of Contents
1. [Overview](#overview)
2. [Components](#components)
3. [Quick Start](#quick-start)
4. [KPI Tracking](#kpi-tracking)
5. [Automated Performance Tracking](#automated-performance-tracking)
6. [Risk Alarm System](#risk-alarm-system)
7. [API Reference](#api-reference)
8. [Integration Guide](#integration-guide)
9. [Configuration](#configuration)
10. [Best Practices](#best-practices)

---

## Overview

The NIJA KPI Dashboard provides comprehensive monitoring and risk management capabilities:

- **KPI Tracking**: Real-time calculation of key performance indicators
- **Automated Performance Tracking**: Background monitoring with periodic reports
- **Risk Alarm System**: Proactive alerts when risk thresholds are breached

### Key Features

✅ **Real-time Metrics**
- Win rate, profit factor, Sharpe ratio
- Drawdown tracking (current & maximum)
- Return metrics (daily, weekly, monthly, total)
- Position exposure and trade frequency

✅ **Automated Monitoring**
- Background thread updates every 60 seconds
- Automatic performance reports every hour
- State persistence across restarts

✅ **Proactive Risk Alarms**
- Drawdown limits
- Daily loss limits
- Win rate degradation
- Position size warnings
- Account balance alerts

---

## Components

### 1. KPI Tracker (`bot/kpi_tracker.py`)

**Purpose**: Calculate and track key performance indicators

**Key Classes**:
- `KPISnapshot`: Point-in-time KPI data
- `KPITracker`: Main tracking engine
- `get_kpi_tracker()`: Singleton accessor

**Tracked KPIs**:
```python
# Return Metrics
- Total Return %
- Daily/Weekly/Monthly Returns
- CAGR (Compound Annual Growth Rate)

# Risk Metrics
- Sharpe Ratio (risk-adjusted returns)
- Sortino Ratio (downside-only risk)
- Maximum Drawdown %
- Current Drawdown %

# Trade Statistics
- Total Trades
- Win Rate %
- Profit Factor
- Average Win/Loss

# Position Metrics
- Active Positions
- Total Exposure %

# Account Metrics
- Account Value
- Cash Balance
- Unrealized P&L
- Realized P&L
```

### 2. Automated Performance Tracker (`bot/automated_performance_tracker.py`)

**Purpose**: Continuous background monitoring

**Key Features**:
- Background thread updates
- Configurable update intervals
- Automatic report generation
- Callback-based data collection

### 3. Risk Alarm System (`bot/risk_alarm_system.py`)

**Purpose**: Proactive risk monitoring and alerts

**Alarm Types**:
- `MAX_DRAWDOWN_EXCEEDED`
- `DAILY_LOSS_LIMIT`
- `CONSECUTIVE_LOSSES`
- `LOW_WIN_RATE`
- `POSITION_SIZE_EXCEEDED`
- `TOTAL_EXPOSURE_EXCEEDED`
- `ACCOUNT_BALANCE_LOW`
- `SHARPE_DEGRADATION`
- `PROFIT_FACTOR_LOW`

**Alarm Levels**:
- `INFO` - Informational
- `WARNING` - Attention needed
- `CRITICAL` - Action required
- `EMERGENCY` - Immediate action required

### 4. KPI Dashboard API (`bot/kpi_dashboard_api.py`)

**Purpose**: RESTful API for dashboard access

**Endpoints**:
```
GET /api/kpi/current        - Current KPI snapshot
GET /api/kpi/history        - Historical KPI data
GET /api/kpi/summary        - KPI summary
GET /api/performance/status - Performance tracker status
GET /api/alarms/active      - Active risk alarms
GET /api/alarms/history     - Alarm history
GET /api/dashboard/overview - Complete dashboard overview
GET /api/health             - Health check
```

---

## Quick Start

### Basic Setup

```python
from bot.kpi_tracker import get_kpi_tracker
from bot.automated_performance_tracker import get_performance_tracker
from bot.risk_alarm_system import get_risk_alarm_system

# Initialize components
kpi_tracker = get_kpi_tracker(initial_capital=10000.0)
performance_tracker = get_performance_tracker(
    update_interval=60,      # Update every 60 seconds
    report_interval=3600     # Report every hour
)
alarm_system = get_risk_alarm_system()
```

### Configure Performance Tracker

```python
# Set callbacks to get account state
performance_tracker.set_account_callbacks(
    account_value_fn=broker.get_account_value,
    cash_balance_fn=broker.get_cash_balance,
    positions_fn=broker.get_positions,
    unrealized_pnl_fn=broker.get_unrealized_pnl,
    realized_pnl_fn=broker.get_total_realized_pnl
)

# Start automated tracking
performance_tracker.start()
```

### Record Trades

```python
# When a trade completes
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
```

### Check Risk Alarms

```python
# Manually check all risks
alarm_system.check_all_risks()

# Get active alarms
active_alarms = alarm_system.get_active_alarms()
for alarm in active_alarms:
    print(f"🚨 {alarm.level}: {alarm.message}")
    print(f"   Action: {alarm.recommended_action}")
```

---

## KPI Tracking

### Manual Updates

```python
# Update KPIs with current state
snapshot = kpi_tracker.update(
    account_value=12500.0,
    cash_balance=5000.0,
    positions=[
        {'symbol': 'BTC-USD', 'value': 5000.0},
        {'symbol': 'ETH-USD', 'value': 2500.0}
    ],
    unrealized_pnl=500.0,
    realized_pnl_total=2500.0
)

print(f"Total Return: {snapshot.total_return_pct:.2f}%")
print(f"Sharpe Ratio: {snapshot.sharpe_ratio:.2f}")
print(f"Win Rate: {snapshot.win_rate_pct:.1f}%")
```

### Get Current KPIs

```python
# Get latest snapshot
current = kpi_tracker.get_current_kpis()

if current:
    print(f"Account Value: ${current.account_value:,.2f}")
    print(f"Total Return: {current.total_return_pct:.2f}%")
    print(f"Max Drawdown: {current.max_drawdown_pct:.2f}%")
    print(f"Win Rate: {current.win_rate_pct:.1f}%")
    print(f"Profit Factor: {current.profit_factor:.2f}")
```

### Get KPI Summary

```python
summary = kpi_tracker.get_kpi_summary()

# Returns structured dictionary
{
    'status': 'active',
    'timestamp': '2026-01-30T10:30:00',
    'returns': {
        'total': 25.5,
        'daily': 1.2,
        'weekly': 5.3,
        'monthly': 18.7
    },
    'risk_metrics': {
        'sharpe_ratio': 1.8,
        'sortino_ratio': 2.1,
        'max_drawdown': 8.3,
        'current_drawdown': 2.1
    },
    'trade_stats': {
        'total_trades': 50,
        'winning_trades': 33,
        'losing_trades': 17,
        'win_rate': 66.0,
        'profit_factor': 1.85
    }
}
```

### Historical Data

```python
# Get last 24 hours of KPI history
history = kpi_tracker.get_kpi_history(hours=24)

# Plot equity curve
import matplotlib.pyplot as plt

timestamps = [kpi.timestamp for kpi in history]
values = [kpi.account_value for kpi in history]

plt.plot(timestamps, values)
plt.title('24-Hour Equity Curve')
plt.show()
```

---

## Automated Performance Tracking

### Configuration

```python
tracker = get_performance_tracker(
    update_interval=60,      # Update every minute
    report_interval=3600     # Generate report every hour
)

# Configure data source callbacks
tracker.set_account_callbacks(
    account_value_fn=get_account_value,
    cash_balance_fn=get_cash_balance,
    positions_fn=get_positions,
    unrealized_pnl_fn=get_unrealized_pnl,
    realized_pnl_fn=get_realized_pnl
)
```

### Control

```python
# Start tracking
tracker.start()

# Pause/Resume
tracker.pause()
tracker.resume()

# Force immediate update
tracker.force_update()

# Force immediate report
tracker.force_report()

# Stop tracking
tracker.stop()
```

### Status Monitoring

```python
status = tracker.get_status()

print(f"Running: {status['running']}")
print(f"Updates: {status['update_count']}")
print(f"Reports: {status['report_count']}")
print(f"Last Update: {status['last_update']}")
```

---

## Risk Alarm System

### Threshold Configuration

```python
from bot.risk_alarm_system import RiskThresholds

# Create custom thresholds
thresholds = RiskThresholds()

# Drawdown limits
thresholds.max_drawdown_pct = 20.0       # Emergency at 20%
thresholds.warning_drawdown_pct = 15.0   # Warning at 15%

# Loss limits
thresholds.daily_loss_limit_pct = 5.0    # Max 5% daily loss
thresholds.consecutive_losses_limit = 5   # Max 5 consecutive losses

# Win rate
thresholds.min_win_rate_pct = 50.0       # Critical below 50%
thresholds.warning_win_rate_pct = 55.0   # Warning below 55%

# Position limits
thresholds.max_position_size_pct = 10.0      # Max 10% per position
thresholds.max_total_exposure_pct = 80.0     # Max 80% total exposure

# Account balance
thresholds.min_account_balance = 100.0       # Emergency below $100
thresholds.warning_account_balance = 500.0   # Warning below $500

# Performance metrics
thresholds.min_sharpe_ratio = 0.5        # Warning below 0.5
thresholds.min_profit_factor = 1.0       # Critical below 1.0

# Create alarm system with custom thresholds
alarm_system = RiskAlarmSystem(thresholds=thresholds)
```

### Manual Risk Checks

```python
# Check all risks
alarm_system.check_all_risks()

# Or check against specific snapshot
snapshot = kpi_tracker.get_current_kpis()
alarm_system.check_all_risks(snapshot)
```

### Active Alarms

```python
# Get all active alarms
active = alarm_system.get_active_alarms()

for alarm in active:
    print(f"🚨 [{alarm.level}] {alarm.alarm_type}")
    print(f"   {alarm.message}")
    print(f"   Current: {alarm.current_value:.2f}")
    print(f"   Threshold: {alarm.threshold_value:.2f}")
    print(f"   Action: {alarm.recommended_action}")
    print()
```

### Alarm History

```python
# Get last 24 hours of alarms
history = alarm_system.get_alarm_history(hours=24)

print(f"Total alarms in last 24h: {len(history)}")

# Group by level
by_level = {}
for alarm in history:
    level = alarm.level
    by_level[level] = by_level.get(level, 0) + 1

print(f"Emergency: {by_level.get('EMERGENCY', 0)}")
print(f"Critical: {by_level.get('CRITICAL', 0)}")
print(f"Warning: {by_level.get('WARNING', 0)}")
```

### Custom Notifications

```python
def send_email_notification(alarm):
    """Send email when alarm triggers"""
    # Your email sending logic here
    print(f"Sending email: {alarm.message}")

def send_webhook_notification(alarm):
    """Send webhook when alarm triggers"""
    # Your webhook logic here
    import requests
    requests.post('https://your-webhook.com/alarm', json=alarm.to_dict())

# Register notification callbacks
alarm_system.add_notification_callback(send_email_notification)
alarm_system.add_notification_callback(send_webhook_notification)
```

---

## API Reference

### REST API Usage

#### Get Current KPIs

```bash
curl http://localhost:5001/api/kpi/current
```

Response:
```json
{
  "success": true,
  "data": {
    "timestamp": "2026-01-30T10:30:00",
    "total_return_pct": 25.5,
    "sharpe_ratio": 1.8,
    "win_rate_pct": 66.0,
    "account_value": 12550.0
  }
}
```

#### Get KPI History

```bash
curl "http://localhost:5001/api/kpi/history?hours=24"
```

#### Get Dashboard Overview

```bash
curl http://localhost:5001/api/dashboard/overview
```

Response:
```json
{
  "success": true,
  "data": {
    "timestamp": "2026-01-30T10:30:00",
    "kpi": { ... },
    "performance_tracking": { ... },
    "risk_alarms": {
      "active_count": 2,
      "has_critical": true,
      "has_warning": true,
      "active_alarms": [...]
    },
    "system_health": {
      "kpi_tracking": "active",
      "performance_tracking": "active",
      "risk_monitoring": "active"
    }
  }
}
```

#### Get Active Alarms

```bash
curl http://localhost:5001/api/alarms/active
```

---

## Integration Guide

### Integration with Trading Bot

```python
# In your main trading bot file

from bot.kpi_tracker import get_kpi_tracker
from bot.automated_performance_tracker import get_performance_tracker
from bot.risk_alarm_system import get_risk_alarm_system

class TradingBot:
    def __init__(self, initial_capital):
        # Initialize components
        self.kpi_tracker = get_kpi_tracker(initial_capital=initial_capital)
        self.performance_tracker = get_performance_tracker()
        self.alarm_system = get_risk_alarm_system()
        
        # Configure performance tracker
        self.performance_tracker.set_account_callbacks(
            account_value_fn=self.get_account_value,
            cash_balance_fn=self.get_cash_balance,
            positions_fn=self.get_positions
        )
        
        # Start automated tracking
        self.performance_tracker.start()
    
    def on_trade_close(self, trade):
        """Called when a trade closes"""
        # Record trade in KPI tracker
        self.kpi_tracker.record_trade(
            symbol=trade.symbol,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            quantity=trade.quantity,
            side=trade.side,
            pnl=trade.pnl,
            entry_time=trade.entry_time,
            exit_time=trade.exit_time,
            fees=trade.fees
        )
        
        # Check risk alarms
        self.alarm_system.check_all_risks()
        
        # Check for emergency alarms
        active_alarms = self.alarm_system.get_active_alarms()
        emergency_alarms = [a for a in active_alarms if a.level == 'EMERGENCY']
        
        if emergency_alarms:
            logger.critical("🚨 EMERGENCY ALARM - STOPPING BOT")
            self.stop_trading()
    
    def get_account_value(self):
        """Get total account value"""
        return self.broker.get_account_value()
    
    def get_cash_balance(self):
        """Get cash balance"""
        return self.broker.get_cash_balance()
    
    def get_positions(self):
        """Get active positions"""
        return self.broker.get_positions()
```

### Integration with Flask App

```python
from flask import Flask
from bot.kpi_dashboard_api import register_kpi_dashboard_routes

app = Flask(__name__)

# Register KPI dashboard routes
register_kpi_dashboard_routes(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
```

---

## Configuration

### Environment Variables

```bash
# KPI Tracker
NIJA_INITIAL_CAPITAL=10000.0
NIJA_KPI_DATA_DIR=./data/kpi

# Performance Tracker
NIJA_PERF_UPDATE_INTERVAL=60
NIJA_PERF_REPORT_INTERVAL=3600
NIJA_PERF_DATA_DIR=./data/performance

# Risk Alarms
NIJA_ALARM_DATA_DIR=./data/risk_alarms
NIJA_MAX_DRAWDOWN=20.0
NIJA_DAILY_LOSS_LIMIT=5.0
NIJA_MIN_WIN_RATE=50.0
```

### Customization

All components support customization through initialization parameters:

```python
# Custom KPI tracker
kpi_tracker = KPITracker(
    initial_capital=50000.0,
    data_dir="./custom/kpi",
    history_size=2000,
    risk_free_rate=0.03  # 3% risk-free rate
)

# Custom performance tracker
perf_tracker = AutomatedPerformanceTracker(
    update_interval=30,      # Update every 30 seconds
    report_interval=1800,    # Report every 30 minutes
    data_dir="./custom/performance"
)

# Custom alarm system
thresholds = RiskThresholds()
thresholds.max_drawdown_pct = 15.0  # Stricter limit

alarm_system = RiskAlarmSystem(
    thresholds=thresholds,
    data_dir="./custom/alarms"
)
```

---

## Best Practices

### 1. Regular Monitoring

```python
# Check dashboard at least daily
summary = kpi_tracker.get_kpi_summary()
if summary['status'] == 'active':
    logger.info(f"Daily Performance: {summary['returns']['daily']:.2f}%")
```

### 2. Alarm Response

```python
# Always check alarms after major events
alarm_system.check_all_risks()

active = alarm_system.get_active_alarms()
if any(a.level in ['CRITICAL', 'EMERGENCY'] for a in active):
    # STOP TRADING
    bot.pause_trading()
    logger.critical("Trading paused due to critical alarms")
```

### 3. Performance Tracking

```python
# Let performance tracker run continuously
tracker.start()

# Only pause during maintenance
# tracker.pause()
# ... maintenance ...
# tracker.resume()
```

### 4. Data Persistence

All components automatically save state to disk. Ensure data directories are:
- Backed up regularly
- Not in version control (.gitignore)
- Monitored for disk space

### 5. API Security

When deploying the API:
- Use HTTPS in production
- Add authentication (API keys, JWT)
- Rate limit endpoints
- Monitor access logs

---

## Troubleshooting

### No KPI Data

```python
# Check if tracker is initialized
tracker = get_kpi_tracker()
current = tracker.get_current_kpis()

if current is None:
    # Need to update with data first
    tracker.update(
        account_value=initial_capital,
        cash_balance=initial_capital,
        positions=[]
    )
```

### Performance Tracker Not Running

```python
# Check status
status = tracker.get_status()

if not status['running']:
    # Check if callbacks configured
    if not status['callbacks_configured']:
        # Configure callbacks first
        tracker.set_account_callbacks(...)
    
    # Then start
    tracker.start()
```

### Alarms Not Triggering

```python
# Manually check risks
alarm_system.check_all_risks()

# Check threshold configuration
thresholds = alarm_system.thresholds
print(f"Max Drawdown Threshold: {thresholds.max_drawdown_pct}%")

# Check cooldown (alarms won't re-trigger within cooldown period)
print(f"Cooldown: {alarm_system.alarm_cooldown_minutes} minutes")
```

---

## Support

For issues, questions, or feature requests:
- Check logs in `./data/` directories
- Review alarm history
- Verify callback functions are working
- Ensure sufficient disk space

## Version History

- v1.0 (2026-01-30): Initial release
  - KPI tracking
  - Automated performance monitoring
  - Risk alarm system
  - RESTful API

---

**NIJA Trading Systems** - Professional Grade Trading Infrastructure
