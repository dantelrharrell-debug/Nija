# Quick Start: KPI Dashboards, Performance Tracking & Risk Alarms

## What Was Added

Three powerful new systems for monitoring and tracking your NIJA trading bot:

1. **KPI Tracker** - Comprehensive performance metrics
2. **Risk Alarm System** - Real-time risk monitoring with configurable alerts
3. **Performance Tracking Service** - Automated background monitoring

## 5-Minute Quick Start

### Step 1: Basic Integration

Add performance tracking to your trading bot:

```python
from bot.performance_tracking_service import get_tracking_service

# Initialize with your starting capital
service = get_tracking_service(initial_capital=1000.0)

# Set up data providers
service.set_balance_provider(lambda: broker.get_balance())
service.set_equity_provider(lambda: broker.get_equity())

# Start the service
service.start()
```

### Step 2: Record Trades

After each trade execution:

```python
service.record_trade(
    symbol=trade.symbol,
    strategy=trade.strategy,
    profit=trade.profit,
    fees=trade.fees,
    is_win=trade.profit > 0,
    entry_price=trade.entry,
    exit_price=trade.exit,
    position_size=trade.size
)
```

### Step 3: Access Dashboard Data

```python
# Get current performance summary
summary = service.get_current_summary()

print(f"Win Rate: {summary['kpis']['win_rate']:.1f}%")
print(f"Profit Factor: {summary['kpis']['profit_factor']:.2f}")
print(f"Active Alarms: {summary['alarms']['total_active']}")

# Export report
report_path = service.export_report()
```

## REST API Quick Start

### Start the API Server

```python
from flask import Flask
from bot.kpi_dashboard_api import register_kpi_dashboard_routes

app = Flask(__name__)
register_kpi_dashboard_routes(app)

app.run(host='0.0.0.0', port=5000)
```

### Access Endpoints

```bash
# Get KPI summary
curl http://localhost:5000/api/v1/kpi/summary

# Get active alarms
curl http://localhost:5000/api/v1/alarms/active

# Get complete dashboard
curl http://localhost:5000/api/v1/dashboard

# Export performance report
curl -X POST http://localhost:5000/api/v1/performance/export
```

## Key Features at a Glance

### KPI Metrics Tracked

- **Performance**: Win rate, profit factor, expectancy
- **Financial**: Net profit, ROI, average win/loss
- **Risk**: Sharpe ratio, Sortino ratio, max drawdown, Calmar ratio
- **Activity**: Trades per day, uptime, active strategies
- **Strategy**: Per-strategy performance breakdown

### Risk Alarms

Default alarms trigger when:
- Balance drops below $50 (CRITICAL) or $100 (WARNING)
- Drawdown exceeds 10% (WARNING) or 20% (CRITICAL)
- Win rate falls below 40% (WARNING) or 30% (CRITICAL)
- Profit factor drops below 1.0 (WARNING)
- Position size exceeds 10% of balance (WARNING)

### Automated Tracking

Background service automatically:
- Collects metrics every 5 minutes
- Calculates full KPIs every hour
- Checks risk alarms every minute
- Persists all data to disk
- Generates comprehensive reports

## Example Output

```
======================================================================
TRADING BOT DASHBOARD
======================================================================

📊 KEY PERFORMANCE INDICATORS
  Total Trades:     50
  Win Rate:         66.7%
  Profit Factor:    2.50
  Net Profit:       $850.00
  ROI:              +85.00%
  Sharpe Ratio:     1.80
  Max Drawdown:     8.5%
  Best Strategy:    APEX_V71

🚨 ACTIVE ALARMS: 1
  WARNING: 1

⚙️ SERVICE STATUS
  Running:          True
  Updates:          12
  KPI Calculations: 1

======================================================================
```

## Files Created

- `bot/kpi_tracker.py` - KPI tracking engine
- `bot/risk_alarm_system.py` - Risk alarm system
- `bot/performance_tracking_service.py` - Automated tracking service
- `bot/kpi_dashboard_api.py` - REST API
- `KPI_DASHBOARD_GUIDE.md` - Complete documentation
- `examples/kpi_dashboard_integration.py` - Full integration example

## Next Steps

1. **Run the example**: `python examples/kpi_dashboard_integration.py`
2. **Review the guide**: See `KPI_DASHBOARD_GUIDE.md` for detailed docs
3. **Integrate with your bot**: Add to your trading strategy
4. **Customize alarms**: Adjust thresholds for your risk tolerance
5. **Set up API**: Deploy the REST API for remote monitoring

## Testing

All modules have been tested:
```bash
# Test KPI tracker
python bot/kpi_tracker.py

# Test risk alarms
python bot/risk_alarm_system.py

# Test tracking service
python bot/performance_tracking_service.py

# Test full integration
python examples/kpi_dashboard_integration.py
```

## Support

- Full documentation: `KPI_DASHBOARD_GUIDE.md`
- Integration example: `examples/kpi_dashboard_integration.py`
- Code is extensively commented and documented

## Security Notes

✅ All components have been security-reviewed:
- Input validation on all API endpoints
- Protected against division by zero
- No Flask debug mode in production
- Error messages sanitized
- CodeQL analysis passed with 0 vulnerabilities

---

**Ready to track your trading performance like a pro!** 🚀
