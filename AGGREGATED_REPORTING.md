# NIJA Aggregated Reporting & Stakeholder Dashboard

## Overview

NIJA provides a comprehensive **read-only aggregation and reporting system** designed for stakeholders, investors, and administrators to monitor the overall performance of the master account and all user accounts in one unified view.

This system addresses three critical needs:
1. **Unified Aggregation View** - Combining master + all users performance
2. **Read-Only Stakeholder Dashboard** - Safe visibility without modification ability
3. **Master-to-User Trade Traceability** - Understanding copy trading performance

---

## Features

### 1. Aggregated Summary Dashboard

**Access**: `http://localhost:5001/reports/aggregated`

A beautiful, auto-refreshing dashboard showing:
- **Portfolio Overview**: Total balance, P&L, trades across master + all users
- **Master Account Performance**: Dedicated section for master trading stats
- **Users Aggregate**: Combined performance of all copy-trading users
- **Individual User Breakdown**: Table showing each user's performance
- **Real-time Updates**: Auto-refresh every 30 seconds

**Key Metrics Displayed**:
- Total Assets Under Management
- Portfolio-wide P&L and ROI %
- Active vs. total users
- Win rates (master vs. users)
- Trade volume and counts

---

## API Endpoints

All aggregation endpoints are **read-only** (GET requests only) and provide JSON responses suitable for integrations with external reporting tools, BI systems, or custom dashboards.

### 1. Aggregated Summary

**Endpoint**: `GET /api/aggregated/summary`

**Description**: Combined overview of master account + all users

**Response Structure**:
```json
{
  "timestamp": "2026-01-21T18:00:00",
  "master_account": {
    "balance": 5000.00,
    "total_pnl": 350.75,
    "daily_pnl": 45.20,
    "win_rate": 62.5,
    "total_trades": 120,
    "winning_trades": 75,
    "losing_trades": 45,
    "open_positions": 3
  },
  "users_aggregate": {
    "total_users": 5,
    "active_users": 4,
    "total_balance": 12500.00,
    "total_pnl": 875.50,
    "total_trades": 300,
    "winning_trades": 195,
    "losing_trades": 105,
    "aggregate_win_rate": 65.0,
    "open_positions": 8
  },
  "portfolio_totals": {
    "total_balance": 17500.00,
    "total_pnl": 1226.25,
    "total_trades": 420,
    "total_open_positions": 11,
    "pnl_return_pct": 7.01
  },
  "user_details": [...]
}
```

**Use Cases**:
- Executive dashboard displays
- Daily performance summaries
- Investor reporting
- Portfolio health checks

---

### 2. Aggregated Performance

**Endpoint**: `GET /api/aggregated/performance?days=7`

**Description**: Detailed performance metrics with daily breakdown

**Query Parameters**:
- `days` (optional, default: 7) - Number of days for breakdown

**Response Structure**:
```json
{
  "timestamp": "2026-01-21T18:00:00",
  "period_days": 7,
  "master_performance": {
    "stats": { ... },
    "daily_breakdown": [
      {
        "date": "2026-01-21",
        "trades": 8,
        "pnl": 45.20,
        "win_rate": 62.5,
        "winners": 5,
        "losers": 3
      },
      ...
    ]
  },
  "users_performance": {
    "daily_breakdown": [ ... ]
  }
}
```

**Use Cases**:
- Performance trend analysis
- Identifying profitable vs. losing days
- Win rate tracking over time
- Strategy effectiveness analysis

---

### 3. Aggregated Positions

**Endpoint**: `GET /api/aggregated/positions`

**Description**: Portfolio-wide position summary

**Response Structure**:
```json
{
  "timestamp": "2026-01-21T18:00:00",
  "summary": {
    "total_positions": 11,
    "master_positions": 3,
    "user_positions": 8,
    "unique_symbols": 5,
    "unique_brokers": 2
  },
  "by_symbol": {
    "BTC-USD": {
      "total_positions": 4,
      "master_positions": 1,
      "user_positions": 3,
      "total_size": 1500.00,
      "total_unrealized_pnl": 45.25
    },
    ...
  },
  "by_broker": {
    "coinbase": {
      "positions": 6,
      "total_size": 5000.00,
      "unrealized_pnl": 125.50
    },
    "kraken": {
      "positions": 5,
      "total_size": 4200.00,
      "unrealized_pnl": 88.75
    }
  },
  "master_positions_list": [ ... ],
  "user_positions_list": [ ... ]
}
```

**Use Cases**:
- Risk exposure analysis
- Symbol concentration monitoring
- Broker diversification assessment
- Real-time P&L tracking

---

### 4. Aggregated Statistics

**Endpoint**: `GET /api/aggregated/statistics`

**Description**: Comprehensive system-wide trading statistics

**Response Structure**:
```json
{
  "timestamp": "2026-01-21T18:00:00",
  "master_statistics": {
    "total_trades": 120,
    "total_pnl": 350.75,
    "total_fees": 25.40,
    "win_rate": 62.5,
    ...
  },
  "users_statistics": {
    "total_trades": 300,
    "total_volume": 75000.00,
    "total_fees": 65.30,
    "total_pnl": 875.50,
    "winning_trades": 195,
    "losing_trades": 105,
    "win_rate": 65.0,
    "average_pnl_per_trade": 2.92
  },
  "system_totals": {
    "total_trades": 420,
    "total_pnl": 1226.25,
    "total_fees": 90.70,
    "net_pnl": 1135.55,
    "total_users": 5
  }
}
```

**Use Cases**:
- All-time performance tracking
- Fee analysis and optimization
- Volume tracking
- ROI calculations

---

### 5. Trade Traceability Report

**Endpoint**: `GET /api/aggregated/traceability?hours=24&limit=50`

**Description**: Master-to-user trade traceability showing how copy trading performs

**Query Parameters**:
- `hours` (optional, default: 24) - Hours to look back
- `limit` (optional, default: 50) - Max master trades to analyze

**Response Structure**:
```json
{
  "timestamp": "2026-01-21T18:00:00",
  "period_hours": 24,
  "summary": {
    "master_trades": 15,
    "total_user_replications": 45,
    "average_replications_per_signal": 3.0
  },
  "traceability": [
    {
      "master_trade": {
        "symbol": "BTC-USD",
        "entry_time": "2026-01-21T15:30:00",
        "entry_price": 68500.00,
        "exit_price": 68750.00,
        "pnl": 25.50,
        "size": 100.00,
        "side": "LONG"
      },
      "user_trades": [
        {
          "user_id": "user_001",
          "entry_time": "2026-01-21T15:30:15",
          "entry_price": 68505.00,
          "exit_price": 68755.00,
          "pnl": 12.75,
          "size": 50.00,
          "time_delay_seconds": 15
        },
        {
          "user_id": "user_002",
          "entry_time": "2026-01-21T15:30:08",
          "entry_price": 68502.00,
          "exit_price": 68752.00,
          "pnl": 15.50,
          "size": 60.00,
          "time_delay_seconds": 8
        }
      ],
      "replication_count": 2,
      "average_delay_seconds": 11.5
    },
    ...
  ]
}
```

**Use Cases**:
- Copy trading performance analysis
- Execution delay tracking
- Replication success rate monitoring
- Master signal effectiveness
- Slippage analysis

**Key Insights**:
- How many users successfully copy each master trade
- Average execution delay from master signal to user execution
- Price differences between master and user entries/exits
- Individual user copy-trading performance

---

## Access Control

### Read-Only Nature

All aggregation endpoints are **strictly read-only**:
- ✅ GET requests only (no POST, PUT, DELETE)
- ✅ No ability to modify trading parameters
- ✅ No ability to trigger trades or kill switches
- ✅ Safe for stakeholder access

### Recommended Access Patterns

1. **Investors/Stakeholders**: Access via the HTML dashboard at `/reports/aggregated`
2. **Automated Reporting**: Poll API endpoints on a schedule (hourly/daily)
3. **BI Tool Integration**: Connect to JSON endpoints for data visualization
4. **Monitoring Systems**: Use for alerting on performance thresholds

---

## Integration Examples

### 1. Python Script for Daily Report

```python
import requests
from datetime import datetime

# Get aggregated summary
response = requests.get('http://localhost:5001/api/aggregated/summary')
data = response.json()

# Extract key metrics
portfolio = data['portfolio_totals']
master = data['master_account']
users = data['users_aggregate']

# Generate report
print(f"NIJA Portfolio Report - {datetime.now().strftime('%Y-%m-%d')}")
print(f"Total Balance: ${portfolio['total_balance']:,.2f}")
print(f"Total P&L: ${portfolio['total_pnl']:,.2f} ({portfolio['pnl_return_pct']:.2f}%)")
print(f"Master Win Rate: {master['win_rate']:.1f}%")
print(f"Users Win Rate: {users['aggregate_win_rate']:.1f}%")
print(f"Active Users: {users['active_users']}/{users['total_users']}")
```

### 2. Excel/Google Sheets Integration

Use the CSV export feature combined with aggregation endpoints:

```bash
# Export trades to CSV
curl "http://localhost:5001/api/trades/export?format=csv&table=completed_trades" \
  -o nija_trades.csv

# Get summary JSON for metrics
curl "http://localhost:5001/api/aggregated/summary" | jq > summary.json
```

### 3. Grafana Dashboard

Create a Grafana dashboard using the JSON API plugin:
- Data source: JSON API
- Endpoints: `/api/aggregated/summary`, `/api/aggregated/performance`
- Refresh interval: 30 seconds
- Visualizations: Time series for P&L, gauges for win rate, tables for users

---

## Security Considerations

### Authentication (Recommended Setup)

While the endpoints are read-only, you should still implement authentication for production:

```python
# Example: Add basic auth to Flask app
from flask_httpauth import HTTPBasicAuth

auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    # Verify against environment variables
    return username == os.getenv('DASHBOARD_USER') and \
           password == os.getenv('DASHBOARD_PASS')

# Protect aggregated routes
@app.route('/api/aggregated/summary')
@auth.login_required
def get_aggregated_summary():
    ...
```

### Network Security

- Run dashboard on internal network only
- Use reverse proxy (nginx) with HTTPS for external access
- Implement IP whitelisting for API access
- Use VPN for remote stakeholder access

---

## Performance Considerations

### Caching

The aggregation endpoints can be resource-intensive with many users. Consider caching:

```python
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@app.route('/api/aggregated/summary')
@cache.cached(timeout=30)  # Cache for 30 seconds
def get_aggregated_summary():
    ...
```

### Pagination

For large datasets, use pagination:
- Trade history: Use `limit` and `offset` parameters
- Traceability: Use `limit` parameter to control result size

---

## Troubleshooting

### Common Issues

**Issue**: "Required modules not available" error
**Solution**: Ensure all user management modules are properly imported:
```bash
# Check imports
python -c "from bot.user_pnl_tracker import get_user_pnl_tracker; print('OK')"
```

**Issue**: Aggregated summary shows 0 users
**Solution**: Verify users are registered in the risk manager:
```bash
# Check user states
python -c "from bot.user_risk_manager import get_user_risk_manager; \
           print(get_user_risk_manager()._user_states.keys())"
```

**Issue**: Traceability shows no replications
**Solution**:
- Check if users are copy-trading from master
- Verify time window (increase `hours` parameter)
- Confirm trades are being recorded in trade ledger

---

## Future Enhancements

Planned features for aggregated reporting:

- [ ] PDF report generation with charts
- [ ] Email digest notifications
- [ ] Webhook alerts for performance thresholds
- [ ] Historical comparison (week-over-week, month-over-month)
- [ ] Advanced analytics (Sharpe ratio, max drawdown, etc.)
- [ ] User cohort analysis
- [ ] Symbol performance ranking
- [ ] Broker performance comparison

---

## Support

For issues or questions about aggregated reporting:
1. Check logs: `tail -f /tmp/nija_monitoring/alerts.json`
2. Verify API health: `curl http://localhost:5001/api/health`
3. Review user states: Check user management documentation

---

**Last Updated**: January 21, 2026
**Version**: 1.0
**Author**: NIJA Trading Systems
