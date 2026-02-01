# Aggregated Reporting Feature - Quick Reference

## What Was Added

This PR adds comprehensive **read-only aggregation and reporting** capabilities to NIJA, addressing the requirement: "Nija and the master need to see read-only aggregation/reporting".

### Three Key Problems Solved

1. ✅ **Unified Aggregation View** - No way to see master + all users combined
2. ✅ **Read-Only Stakeholder Dashboard** - No safe view for non-technical stakeholders
3. ✅ **Master-to-User Trade Traceability** - No visibility into copy trading effectiveness

## Quick Start

### For Stakeholders (Non-Technical)

1. Start the dashboard server:
   ```bash
   python bot/dashboard_server.py
   ```

2. Open your browser to:
   ```
   http://localhost:5001/reports/aggregated
   ```

3. You'll see:
   - Portfolio balance and P&L
   - Platform account performance
   - All users' combined performance
   - Individual user breakdown table
   - Auto-refreshes every 30 seconds

### For Developers/Integrations

**New API Endpoints** (all read-only):

```bash
# Portfolio overview
curl http://localhost:5001/api/aggregated/summary

# Performance with daily breakdown (7 days)
curl http://localhost:5001/api/aggregated/performance?days=7

# Portfolio-wide positions by symbol/broker
curl http://localhost:5001/api/aggregated/positions

# System-wide statistics
curl http://localhost:5001/api/aggregated/statistics

# Master-to-user trade traceability (last 24 hours)
curl http://localhost:5001/api/aggregated/traceability?hours=24&limit=50
```

## What Each Endpoint Shows

### `/api/aggregated/summary`
- Platform account: balance, P&L, win rate, trades
- Users aggregate: total balance, combined P&L, win rate
- Portfolio totals: total balance, total P&L, ROI %
- Individual user list with stats

### `/api/aggregated/performance`
- Master daily breakdown (trades, P&L, win rate per day)
- Users combined daily breakdown
- Customizable time period (default 7 days)

### `/api/aggregated/positions`
- All open positions across master + users
- Aggregated by symbol (how many positions per symbol)
- Aggregated by broker (Coinbase, Kraken, etc.)
- Separate lists for master vs. user positions

### `/api/aggregated/statistics`
- Master all-time stats (trades, volume, fees, P&L)
- Users combined stats
- System totals (master + users)

### `/api/aggregated/traceability`
- Shows which master trades were copied by which users
- Execution delay (time from master trade to user trade)
- Replication count per signal
- Copy trading effectiveness metrics

## Example Use Cases

### 1. Daily Performance Report

```python
import requests
import json

response = requests.get('http://localhost:5001/api/aggregated/summary')
data = response.json()

print(f"Portfolio Balance: ${data['portfolio_totals']['total_balance']:,.2f}")
print(f"Total P&L: ${data['portfolio_totals']['total_pnl']:,.2f}")
print(f"ROI: {data['portfolio_totals']['pnl_return_pct']:.2f}%")
print(f"Master Win Rate: {data['master_account']['win_rate']:.1f}%")
print(f"Users Win Rate: {data['users_aggregate']['aggregate_win_rate']:.1f}%")
```

### 2. Export to CSV for Excel

```bash
# Get data
curl http://localhost:5001/api/aggregated/summary > portfolio_summary.json

# Convert to CSV using jq
cat portfolio_summary.json | jq -r '.user_details[] | [.user_id, .balance, .total_pnl, .win_rate, .trades] | @csv' > users.csv
```

### 3. Monitoring Copy Trading Performance

```python
import requests

response = requests.get('http://localhost:5001/api/aggregated/traceability?hours=24')
data = response.json()

summary = data['summary']
print(f"Master traded {summary['master_trades']} times")
print(f"Users replicated {summary['total_user_replications']} trades total")
print(f"Average {summary['average_replications_per_signal']:.1f} users copy each signal")

# Check which trades were not replicated
for trade in data['traceability']:
    if trade['replication_count'] == 0:
        print(f"⚠️  No users copied: {trade['master_trade']['symbol']} at {trade['master_trade']['entry_time']}")
```

## Testing

Run the provided test script:

```bash
./test_aggregated_reporting.sh
```

This will:
- Check if server is running
- Test all 5 aggregated endpoints
- Verify the HTML dashboard is accessible
- Show sample responses

## Files Modified/Created

- `bot/user_dashboard_api.py` - Added 5 aggregation endpoints
- `bot/dashboard_server.py` - Added `/reports/aggregated` route
- `bot/templates/aggregated_report.html` - Stakeholder dashboard UI
- `AGGREGATED_REPORTING.md` - Full documentation (12KB)
- `test_aggregated_reporting.sh` - Testing script

## Security Notes

- All endpoints are **read-only** (GET requests only)
- No POST/PUT/DELETE operations
- No trading controls exposed
- No ability to modify risk limits
- Safe for stakeholder access

## Next Steps

1. Review `AGGREGATED_REPORTING.md` for complete documentation
2. Start dashboard server: `python bot/dashboard_server.py`
3. Access stakeholder view: http://localhost:5001/reports/aggregated
4. Test API endpoints with curl or in your application

## Support

- Full API docs: `AGGREGATED_REPORTING.md`
- Integration examples: See documentation file
- Test script: `./test_aggregated_reporting.sh`
