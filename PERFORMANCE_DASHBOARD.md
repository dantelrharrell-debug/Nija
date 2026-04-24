# NIJA Performance Dashboard

## Overview

The NIJA Performance Dashboard provides investor-grade performance tracking and reporting. This is capital-raising infrastructure designed to provide institutional-quality metrics and reports.

## Features

### Core Metrics

1. **Daily NAV Tracking**
   - Net Asset Value calculation
   - Total equity tracking
   - Cash and positions breakdown

2. **Equity Curves**
   - Historical equity performance
   - Time-series equity data
   - Customizable date ranges

3. **Drawdown Curves**
   - Real-time drawdown tracking
   - Maximum drawdown identification
   - Drawdown recovery periods

4. **Sharpe Ratio Tracking**
   - Daily Sharpe ratio calculation
   - Sortino ratio (downside-only risk)
   - Risk-adjusted returns

5. **Monthly Performance Reports**
   - Month-by-month breakdown
   - Return analysis
   - Risk metrics per month

## Components

### 1. Performance Metrics Calculator (`bot/performance_metrics.py`)

Core calculation engine for all performance metrics.

**Key Classes:**
- `PerformanceSnapshot` - Point-in-time performance data
- `PerformanceMetrics` - Comprehensive metrics bundle
- `PerformanceMetricsCalculator` - Main calculator

**Metrics Calculated:**
- Total return %
- Daily/Monthly/Annualized returns
- Sharpe ratio
- Sortino ratio
- Maximum drawdown
- Current drawdown
- Win rate
- Trade statistics
- Volatility metrics

### 2. Performance Dashboard (`bot/performance_dashboard.py`)

High-level dashboard interface for investor reporting.

**Key Features:**
- Real-time NAV tracking
- Equity curve generation
- Drawdown curve visualization
- Monthly report generation
- Strategy performance breakdown
- Investor summary reports

### 3. Dashboard API (`bot/dashboard_api.py`)

Flask API endpoints for accessing dashboard data.

**Endpoints:**
- `GET /api/v1/dashboard/metrics` - Current metrics
- `GET /api/v1/dashboard/equity-curve` - Equity curve data
- `GET /api/v1/dashboard/drawdown-curve` - Drawdown data
- `GET /api/v1/dashboard/monthly-report/<year>/<month>` - Monthly report
- `GET /api/v1/dashboard/investor-summary` - Full investor summary
- `POST /api/v1/dashboard/update-snapshot` - Update performance data

### 4. Database Models (`database/models.py`)

Extended with performance tracking tables:
- `PerformanceSnapshot` - Historical snapshots
- `StrategyPerformance` - Strategy-level metrics
- `MonthlyReport` - Monthly aggregated reports

## Usage

### Basic Setup

```python
from bot.performance_dashboard import get_performance_dashboard

# Initialize dashboard
dashboard = get_performance_dashboard(
    initial_capital=10000.0,
    user_id="user123"
)
```

### Recording Performance Data

```python
# Update snapshot with current portfolio state
dashboard.update_snapshot(
    cash=8000.0,
    positions_value=4500.0,
    unrealized_pnl=500.0,
    realized_pnl_today=100.0,
    total_trades=50,
    winning_trades=32,
    losing_trades=18
)
```

### Getting Current Metrics

```python
# Get current performance metrics
metrics = dashboard.get_current_metrics()

print(f"Total Return: {metrics['total_return_pct']:.2f}%")
print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {metrics['max_drawdown_pct']:.2f}%")
print(f"Win Rate: {metrics['win_rate_pct']:.2f}%")
```

### Generating Equity Curve

```python
# Get equity curve for last 30 days
equity_curve = dashboard.get_equity_curve(days=30)

# Plot using your preferred library
timestamps = [point['timestamp'] for point in equity_curve]
equity = [point['equity'] for point in equity_curve]
```

### Monthly Reports

```python
# Get monthly report
report = dashboard.get_monthly_report(year=2026, month=1)

print(f"Monthly Return: {report['monthly_return_pct']:.2f}%")
print(f"Trades: {report['total_trades']}")
print(f"Win Rate: {report['win_rate_pct']:.2f}%")

# Get all monthly reports
all_reports = dashboard.get_all_monthly_reports()
```

### Investor Summary

```python
# Generate comprehensive investor summary
summary = dashboard.get_investor_summary()

# Export to file
filepath = dashboard.export_investor_report(output_dir='./reports')
print(f"Report saved to: {filepath}")
```

## API Integration

### Flask App Integration

```python
from flask import Flask
from bot.dashboard_api import register_dashboard_routes

app = Flask(__name__)

# Register dashboard routes
register_dashboard_routes(app)

if __name__ == '__main__':
    app.run(port=5000)
```

### API Usage Examples

#### Get Current Metrics

```bash
curl http://localhost:5000/api/v1/dashboard/metrics
```

Response:
```json
{
  "success": true,
  "data": {
    "total_return_pct": 25.5,
    "annualized_return_pct": 45.2,
    "sharpe_ratio": 1.8,
    "max_drawdown_pct": 8.3,
    "win_rate_pct": 64.0
  }
}
```

#### Get Equity Curve

```bash
curl "http://localhost:5000/api/v1/dashboard/equity-curve?days=30"
```

#### Update Snapshot

```bash
curl -X POST http://localhost:5000/api/v1/dashboard/update-snapshot \
  -H "Content-Type: application/json" \
  -d '{
    "cash": 8000.0,
    "positions_value": 4500.0,
    "unrealized_pnl": 500.0,
    "realized_pnl_today": 100.0,
    "total_trades": 50,
    "winning_trades": 32,
    "losing_trades": 18
  }'
```

#### Get Investor Summary

```bash
curl http://localhost:5000/api/v1/dashboard/investor-summary
```

Response:
```json
{
  "success": true,
  "data": {
    "user_id": "user123",
    "initial_capital": 10000.0,
    "current_nav": 12550.0,
    "total_return_pct": 25.5,
    "annualized_return_pct": 45.2,
    "sharpe_ratio": 1.8,
    "sortino_ratio": 2.1,
    "max_drawdown_pct": 8.3,
    "win_rate_pct": 64.0,
    "total_trades": 50,
    "active_strategies": 3,
    "diversification_score": 78.5
  }
}
```

## Performance Metrics Explained

### NAV (Net Asset Value)
Total portfolio value including cash and positions:
```
NAV = Cash + Positions Market Value
```

### Equity
Total capital available (same as NAV in this context):
```
Equity = Cash + Positions Value
```

### Sharpe Ratio
Risk-adjusted return metric:
```
Sharpe = (Return - Risk_Free_Rate) / Volatility
```
- **> 1.0** - Good risk-adjusted returns
- **> 2.0** - Excellent risk-adjusted returns
- **> 3.0** - Outstanding risk-adjusted returns

### Sortino Ratio
Like Sharpe but only penalizes downside volatility:
```
Sortino = (Return - Risk_Free_Rate) / Downside_Deviation
```
- Generally higher than Sharpe ratio
- Better measure for asymmetric strategies

### Maximum Drawdown
Largest peak-to-trough decline:
```
Max_DD = (Peak - Trough) / Peak × 100%
```
- **< 10%** - Excellent
- **10-20%** - Good
- **20-30%** - Acceptable
- **> 30%** - High risk

### Win Rate
Percentage of winning trades:
```
Win_Rate = Winning_Trades / Total_Trades × 100%
```
- **> 50%** - Profitable on average
- **> 60%** - Very good
- **> 70%** - Excellent

## Investor Report Format

The investor report includes:

1. **Executive Summary**
   - Initial capital
   - Current NAV
   - Total return
   - Annualized return

2. **Performance Metrics**
   - Sharpe and Sortino ratios
   - Maximum drawdown
   - Win rate
   - Trading activity

3. **Risk Metrics**
   - Current drawdown
   - Volatility
   - Drawdown history

4. **Portfolio Composition**
   - Active strategies
   - Strategy allocations
   - Diversification score

5. **Time Series Data**
   - Equity curve
   - Drawdown curve
   - Monthly reports

## Dashboard Update Frequency

- **Snapshots**: Every 1 hour (configurable)
- **Metrics**: Real-time calculation
- **Monthly Reports**: Generated on-demand
- **Persistence**: Auto-saved to disk

## Best Practices

### 1. Regular Snapshot Updates
```python
# In your trading loop
if time_for_snapshot():
    dashboard.update_snapshot(
        cash=get_cash(),
        positions_value=get_positions_value(),
        unrealized_pnl=get_unrealized_pnl(),
        realized_pnl_today=get_realized_pnl_today(),
        total_trades=trade_count,
        winning_trades=win_count,
        losing_trades=loss_count
    )
```

### 2. Periodic State Saving
```python
# Save state periodically
dashboard.save_state()
```

### 3. Monthly Report Generation
```python
# Generate at end of month
from datetime import datetime

now = datetime.now()
report = dashboard.get_monthly_report(now.year, now.month)
```

### 4. Investor Communications
```python
# Export report for investors
filepath = dashboard.export_investor_report()
send_to_investors(filepath)
```

## Customization

### Snapshot Interval
```python
dashboard.snapshot_interval = timedelta(minutes=30)  # 30 min snapshots
```

### Risk-Free Rate
```python
# Adjust for Sharpe calculation
metrics_calculator = dashboard.metrics_calculator
sharpe = metrics_calculator.calculate_sharpe_ratio(risk_free_rate=0.03)  # 3%
```

### Custom Metrics
Extend `PerformanceMetricsCalculator` to add custom metrics:

```python
class CustomMetricsCalculator(PerformanceMetricsCalculator):
    def calculate_calmar_ratio(self):
        """Calmar ratio = Annualized Return / Max Drawdown"""
        metrics = self.calculate_metrics()
        if metrics.max_drawdown_pct > 0:
            return metrics.annualized_return_pct / metrics.max_drawdown_pct
        return 0.0
```

## Troubleshooting

### Missing Data
- Ensure snapshots are being recorded regularly
- Check that initial_capital is set correctly
- Verify database connections if using DB storage

### Incorrect Metrics
- Validate input data (cash, positions_value, etc.)
- Check that timestamps are in correct order
- Ensure trades are being counted correctly

### API Errors
- Check Flask app is running
- Verify route registration
- Review error logs

## Future Enhancements

- [ ] Real-time WebSocket updates
- [ ] Advanced charting integration
- [ ] PDF report generation
- [ ] Email report delivery
- [ ] Benchmark comparison (S&P 500, BTC)
- [ ] Risk-adjusted performance attribution
- [ ] Monte Carlo simulations
- [ ] Stress testing capabilities

## Related Documentation

- [Capital Scaling Framework](CAPITAL_SCALING_FRAMEWORK.md)
- [Strategy Portfolio](STRATEGY_PORTFOLIO.md)
- [Database Setup](DATABASE_SETUP.md)
