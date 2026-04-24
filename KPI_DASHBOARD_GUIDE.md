# NIJA KPI Dashboards, Performance Tracking & Risk Alarms

## Overview

This document describes the comprehensive KPI (Key Performance Indicator) dashboard system, automated performance tracking service, and risk alarm system implemented for the NIJA trading bot.

## Table of Contents

1. [Features](#features)
2. [Components](#components)
3. [Getting Started](#getting-started)
4. [API Reference](#api-reference)
5. [Configuration](#configuration)
6. [Usage Examples](#usage-examples)
7. [Integration Guide](#integration-guide)

---

## Features

### 1. KPI Dashboards

Track comprehensive trading performance metrics:

- **Trading Performance KPIs**
  - Total trades, wins, losses
  - Win rate percentage
  - Profit factor
  - Expectancy

- **Financial KPIs**
  - Total profit/loss
  - Net profit (after fees)
  - Average win/loss
  - ROI percentage

- **Risk KPIs**
  - Sharpe ratio
  - Sortino ratio
  - Maximum drawdown
  - Calmar ratio

- **Efficiency KPIs**
  - Risk-reward ratio
  - Profit per trade
  - Trades per day

- **Strategy KPIs**
  - Per-strategy performance
  - Best/worst strategies
  - Strategy comparison

### 2. Automated Performance Tracking

Background service that continuously monitors and tracks:

- Real-time performance metrics collection
- Scheduled KPI calculations (configurable intervals)
- Automated risk alarm checks
- Historical data persistence
- Periodic report generation

### 3. Risk Alarm System

Comprehensive risk monitoring with configurable alarms:

- **Balance Alarms**
  - Critical balance threshold
  - Low balance warning
  - Significant balance drops

- **Drawdown Alarms**
  - Maximum drawdown exceeded
  - High drawdown warnings

- **Performance Alarms**
  - Low win rate
  - Poor profit factor
  - Negative expectancy

- **Position Alarms**
  - Excessive position size
  - High total exposure

- **Alarm Management**
  - Multiple severity levels (INFO, WARNING, CRITICAL, EMERGENCY)
  - Alarm acknowledgment
  - Historical alarm logging
  - Configurable thresholds

---

## Components

### 1. KPI Tracker (`bot/kpi_tracker.py`)

Core module for tracking and calculating KPIs.

**Key Classes:**
- `KPISnapshot` - Immutable KPI snapshot at a point in time
- `KPITracker` - Main KPI tracking and calculation engine

**Key Features:**
- Trade recording with strategy attribution
- Balance and equity tracking
- Automatic KPI calculation
- Historical KPI snapshots
- Export to JSON

**Example:**
```python
from bot.kpi_tracker import get_kpi_tracker

# Initialize tracker
tracker = get_kpi_tracker(initial_capital=1000.0)

# Record a trade
tracker.record_trade(
    symbol="BTC-USD",
    strategy="APEX_V71",
    profit=50.0,
    fees=1.0,
    is_win=True,
    entry_price=45000,
    exit_price=46000,
    position_size=0.1
)

# Update balance
tracker.update_balance(balance=1049.0, equity=1049.0)

# Calculate KPIs
kpis = tracker.calculate_kpis(current_balance=1049.0, current_equity=1049.0)

# Get summary
summary = tracker.get_kpi_summary()
print(f"Win Rate: {summary['win_rate']:.1f}%")
print(f"Profit Factor: {summary['profit_factor']:.2f}")

# Export
tracker.export_kpis()
```

### 2. Risk Alarm System (`bot/risk_alarm_system.py`)

Risk monitoring and alarm triggering system.

**Key Classes:**
- `AlarmThreshold` - Configurable threshold definition
- `Alarm` - Alarm event with metadata
- `RiskAlarmSystem` - Main alarm management engine

**Alarm Severity Levels:**
- `INFO` - Informational only
- `WARNING` - Action may be needed
- `CRITICAL` - Immediate attention required
- `EMERGENCY` - Severe condition, stop trading

**Alarm Categories:**
- `BALANCE` - Balance-related
- `DRAWDOWN` - Drawdown-related
- `POSITION` - Position sizing
- `TRADE_PERFORMANCE` - Trading performance
- `VOLATILITY` - Market volatility
- `SYSTEM` - System health
- `API` - API errors
- `STRATEGY` - Strategy performance

**Example:**
```python
from bot.risk_alarm_system import get_risk_alarm_system

# Initialize alarm system
alarm_system = get_risk_alarm_system()

# Check balance alarms
alarm_system.check_balance_alarms(
    current_balance=45.0,
    peak_balance=100.0
)

# Check performance alarms
alarm_system.check_performance_alarms(
    win_rate=35.0,
    profit_factor=0.8
)

# Get active alarms
active_alarms = alarm_system.get_active_alarms(severity="CRITICAL")

# Acknowledge an alarm
alarm_system.acknowledge_alarm(alarm_id="critical_balance_20260130_120000")

# Get summary
summary = alarm_system.get_alarm_summary()
print(f"Active Alarms: {summary['total_active']}")
```

### 3. Performance Tracking Service (`bot/performance_tracking_service.py`)

Automated background service for continuous performance monitoring.

**Key Classes:**
- `PerformanceTrackingService` - Main service class

**Key Features:**
- Runs in background thread
- Configurable update intervals
- Automatic KPI calculations
- Scheduled alarm checks
- Comprehensive reporting

**Example:**
```python
from bot.performance_tracking_service import get_tracking_service

# Initialize service
service = get_tracking_service(initial_capital=1000.0)

# Set up data providers
def get_balance():
    return broker.get_account_balance()

def get_equity():
    return broker.get_account_equity()

service.set_balance_provider(get_balance)
service.set_equity_provider(get_equity)

# Record trades
service.record_trade(
    symbol="BTC-USD",
    strategy="APEX_V71",
    profit=50.0,
    fees=1.0,
    is_win=True,
    entry_price=45000,
    exit_price=46000,
    position_size=0.1
)

# Start service
service.start()

# Get status
status = service.get_status()
print(f"Running: {status['running']}")
print(f"Updates: {status['updates_count']}")

# Get comprehensive summary
summary = service.get_current_summary()

# Export report
report_path = service.export_report()

# Stop service when done
service.stop()
```

### 4. KPI Dashboard API (`bot/kpi_dashboard_api.py`)

REST API for accessing KPI, alarm, and performance data.

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/kpi/summary` | Get current KPI summary |
| GET | `/api/v1/kpi/trends?days=30` | Get KPI trends over time |
| POST | `/api/v1/kpi/export` | Export KPIs to file |
| GET | `/api/v1/alarms/active` | Get active alarms |
| GET | `/api/v1/alarms/summary` | Get alarm summary |
| POST | `/api/v1/alarms/<id>/acknowledge` | Acknowledge alarm |
| POST | `/api/v1/alarms/<id>/clear` | Clear alarm |
| GET | `/api/v1/performance/status` | Get service status |
| GET | `/api/v1/performance/summary` | Get performance summary |
| POST | `/api/v1/performance/export` | Export performance report |
| GET | `/api/v1/dashboard` | Get complete dashboard data |
| GET | `/api/v1/health` | Health check |

**Example:**
```python
from flask import Flask
from bot.kpi_dashboard_api import register_kpi_dashboard_routes

app = Flask(__name__)
register_kpi_dashboard_routes(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

---

## Getting Started

### Installation

All modules are included in the NIJA bot. No additional installation required.

### Quick Start

1. **Initialize the system:**

```python
from bot.performance_tracking_service import get_tracking_service

# Start with your initial capital
service = get_tracking_service(initial_capital=1000.0)
```

2. **Set up data providers:**

```python
# Provide functions to get current balance and equity
service.set_balance_provider(lambda: broker.get_balance())
service.set_equity_provider(lambda: broker.get_equity())
```

3. **Start the service:**

```python
service.start()
```

4. **Record trades as they occur:**

```python
# After each trade
service.record_trade(
    symbol=symbol,
    strategy=strategy_name,
    profit=profit,
    fees=fees,
    is_win=is_profitable,
    entry_price=entry,
    exit_price=exit,
    position_size=size
)
```

5. **Access dashboard via API:**

```bash
# Get dashboard summary
curl http://localhost:5000/api/v1/dashboard

# Get active alarms
curl http://localhost:5000/api/v1/alarms/active

# Export performance report
curl -X POST http://localhost:5000/api/v1/performance/export
```

---

## API Reference

### KPI Summary Response

```json
{
  "success": true,
  "data": {
    "timestamp": "2026-01-30T04:30:00",
    "total_trades": 50,
    "winning_trades": 33,
    "losing_trades": 17,
    "win_rate": 66.0,
    "profit_factor": 2.5,
    "total_profit": 1500.0,
    "total_loss": 600.0,
    "net_profit": 850.0,
    "total_fees": 50.0,
    "average_win": 45.45,
    "average_loss": 35.29,
    "sharpe_ratio": 1.8,
    "sortino_ratio": 2.1,
    "max_drawdown": 8.5,
    "current_drawdown": 2.1,
    "calmar_ratio": 3.2,
    "expectancy": 17.0,
    "risk_reward_ratio": 1.29,
    "profit_per_trade": 17.0,
    "roi_percentage": 85.0,
    "trades_per_day": 2.5,
    "active_days": 20,
    "account_balance": 1850.0,
    "account_equity": 1850.0,
    "account_growth": 85.0,
    "active_strategies": 2,
    "best_strategy": "APEX_V71",
    "worst_strategy": "DUAL_RSI"
  }
}
```

### Alarm Summary Response

```json
{
  "success": true,
  "data": {
    "total_active": 3,
    "total_acknowledged": 1,
    "active_by_severity": {
      "INFO": 0,
      "WARNING": 2,
      "CRITICAL": 1,
      "EMERGENCY": 0
    },
    "active_by_category": {
      "BALANCE": 1,
      "DRAWDOWN": 1,
      "TRADE_PERFORMANCE": 1
    },
    "total_historical": 15,
    "last_alarm": "2026-01-30T04:25:00"
  }
}
```

### Dashboard Data Response

```json
{
  "success": true,
  "data": {
    "kpis": { /* KPI summary */ },
    "alarms": {
      "summary": { /* Alarm summary */ },
      "active": [
        {
          "alarm_id": "high_drawdown_20260130_042500",
          "severity": "WARNING",
          "category": "DRAWDOWN",
          "message": "Drawdown exceeds 10%",
          "timestamp": "2026-01-30T04:25:00"
        }
      ]
    },
    "service": {
      "running": true,
      "uptime_seconds": 3600,
      "updates_count": 12,
      "kpi_calculations_count": 1
    }
  }
}
```

---

## Configuration

### Alarm Thresholds

Default thresholds can be customized:

```python
from bot.risk_alarm_system import get_risk_alarm_system, AlarmThreshold, AlarmSeverity, AlarmCategory

alarm_system = get_risk_alarm_system()

# Add custom threshold
custom_threshold = AlarmThreshold(
    name="custom_win_rate",
    category=AlarmCategory.TRADE_PERFORMANCE.value,
    severity=AlarmSeverity.WARNING.value,
    threshold_value=50.0,
    comparison='lt',
    description="Win rate below 50%"
)

alarm_system.add_threshold(custom_threshold)
```

### Service Intervals

Customize update intervals:

```python
from bot.performance_tracking_service import PerformanceTrackingService

service = PerformanceTrackingService(
    initial_capital=1000.0,
    update_interval_seconds=60,      # Update every 1 minute
    kpi_calculation_interval_seconds=1800,  # Calculate KPIs every 30 min
    alarm_check_interval_seconds=30   # Check alarms every 30 seconds
)
```

---

## Usage Examples

### Example 1: Basic Integration

```python
from bot.performance_tracking_service import get_tracking_service

# Initialize
service = get_tracking_service(initial_capital=1000.0)

# In your trading loop
def on_trade_complete(trade):
    service.record_trade(
        symbol=trade.symbol,
        strategy=trade.strategy,
        profit=trade.profit,
        fees=trade.fees,
        is_win=trade.profit > 0,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        position_size=trade.size
    )

# Start service
service.start()
```

### Example 2: Custom Alarm Callbacks

```python
from bot.risk_alarm_system import get_risk_alarm_system

alarm_system = get_risk_alarm_system()

# Register callback for critical alarms
def on_critical_alarm(alarm):
    if alarm.severity == "CRITICAL":
        # Send email, SMS, or stop trading
        notify_admin(f"CRITICAL: {alarm.message}")
        if alarm.category == "BALANCE":
            trading_bot.pause()

alarm_system.register_callback(on_critical_alarm)
```

### Example 3: Generate Daily Reports

```python
from bot.performance_tracking_service import get_tracking_service
import schedule
import time

service = get_tracking_service()

def generate_daily_report():
    report_path = service.export_report()
    send_email_report(report_path)

# Schedule daily report at 11:59 PM
schedule.every().day.at("23:59").do(generate_daily_report)

# Run scheduler
while True:
    schedule.run_pending()
    time.sleep(60)
```

---

## Integration Guide

### Integration with Trading Strategy

```python
from bot.trading_strategy import TradingStrategy
from bot.performance_tracking_service import get_tracking_service

class MyStrategy(TradingStrategy):
    def __init__(self):
        super().__init__()
        self.tracking_service = get_tracking_service(initial_capital=1000.0)
        self.tracking_service.start()
    
    def on_trade_close(self, trade):
        # Record trade for KPI tracking
        self.tracking_service.record_trade(
            symbol=trade.symbol,
            strategy=self.strategy_name,
            profit=trade.profit,
            fees=trade.fees,
            is_win=trade.is_profitable,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            position_size=trade.size
        )
```

### Integration with Dashboard API

```python
from flask import Flask
from bot.kpi_dashboard_api import register_kpi_dashboard_routes
from bot.performance_tracking_service import get_tracking_service

# Initialize service
tracking_service = get_tracking_service(initial_capital=1000.0)
tracking_service.start()

# Create Flask app with dashboard routes
app = Flask(__name__)
register_kpi_dashboard_routes(app)

# Add your own routes
@app.route('/start_trading', methods=['POST'])
def start_trading():
    # Your trading logic
    pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

---

## Best Practices

1. **Always start the tracking service early** in your bot's initialization
2. **Record every trade** to ensure accurate KPIs
3. **Set appropriate alarm thresholds** for your risk tolerance
4. **Acknowledge alarms** after taking action to keep dashboard clean
5. **Export reports regularly** for record keeping
6. **Monitor KPI trends** not just current values
7. **Use alarm callbacks** for automated responses to critical conditions

---

## Troubleshooting

### Issue: No KPIs showing

**Solution:** Ensure you've recorded at least one trade and updated balance.

### Issue: Alarms not triggering

**Solution:** Check that alarm thresholds are enabled and alarm check interval has elapsed.

### Issue: Service not updating

**Solution:** Verify data providers are set and returning valid data.

### Issue: API endpoints not responding

**Solution:** Ensure Flask app is running and routes are registered.

---

## Future Enhancements

- [ ] Real-time WebSocket updates for dashboard
- [ ] Email/SMS notifications for critical alarms
- [ ] PDF report generation
- [ ] Advanced charting and visualization
- [ ] Machine learning-based anomaly detection
- [ ] Benchmark comparison (vs BTC, S&P 500)
- [ ] Multi-timeframe analysis
- [ ] Strategy correlation analysis

---

## Support

For issues or questions:
- Check the code documentation
- Review the test files for examples
- Raise an issue on GitHub

---

## License

Part of the NIJA Trading Bot - All Rights Reserved
