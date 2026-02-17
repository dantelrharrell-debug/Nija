# NIJA MICRO_CAP Production Readiness Dashboard

## Screenshot

![NIJA MICRO_CAP Dashboard](https://github.com/user-attachments/assets/e16de079-2089-4bc0-9aef-22f6bd97d92c)

## Overview

The **NIJA MICRO_CAP Production Readiness Dashboard** is a real-time monitoring interface designed specifically for tracking the first 50 trades in MICRO_CAP mode. It provides comprehensive visibility into:

- 💰 **Balances**: Cash, equity, available capital, and reserved buffer
- 🔒 **Held Capital**: Open positions value, count, and exposure
- 📋 **Open Orders**: Active positions with real-time P&L
- 📈 **Expectancy**: Win rate, profit factor, average win/loss
- 📉 **Drawdown**: Current and maximum drawdown tracking
- ⚠️ **Compliance Alerts**: Risk violations and position limit warnings

## Features

### Real-Time Monitoring
- Auto-refresh every 5 seconds
- Live connection status indicator
- Timestamp tracking for last update

### Trade Progress Tracking
- Visual progress bar showing trades executed out of 50
- Real-time trade counter
- Expectancy calculations updated with each trade

### Risk Management
- Drawdown monitoring with visual alerts
- Compliance alert system for rule violations
- Position limit tracking
- Exposure percentage monitoring

### Visual Indicators
- Color-coded alerts (green=good, yellow=warning, red=critical)
- Large metric displays for key values
- Clean, professional interface

## Installation

No additional installation required - the dashboard uses standard NIJA dependencies.

## Usage

### Starting the Dashboard

#### Option 1: Using the startup script (recommended)
```bash
./start_micro_cap_dashboard.sh
```

#### Option 2: Manual start
```bash
python3 micro_cap_dashboard_api.py
```

#### Option 3: Custom port
```bash
DASHBOARD_PORT=8080 python3 micro_cap_dashboard_api.py
```

### Accessing the Dashboard

Once started, access the dashboard at:
- **Dashboard URL**: http://localhost:5002/dashboard
- **API Endpoint**: http://localhost:5002/api/v1/dashboard/micro-cap

### Stopping the Dashboard

Press `Ctrl+C` in the terminal where the dashboard is running.

## Dashboard Sections

### 1. Trade Progress
Shows progress toward 50 trades with a visual progress bar and percentage.

### 2. Balances Card (💰)
- **Cash Balance**: Available USD in account
- **Account Equity**: Total account value (cash + positions)
- **Available Capital**: Cash minus reserved buffer
- **Reserved Buffer**: 15% reserve for MICRO_CAP mode

### 3. Held Capital Card (🔒)
- **Positions Value**: Total market value of open positions
- **Open Positions**: Number of currently open positions
- **Unrealized P&L**: Profit/loss on open positions
- **Exposure %**: Percentage of equity in open positions

### 4. Expectancy Card (📈)
- **Win Rate**: Percentage of winning trades
- **Profit Factor**: Ratio of gross profit to gross loss
- **Avg Win**: Average profit per winning trade
- **Avg Loss**: Average loss per losing trade

### 5. Drawdown Tracker (📉)
- **Current Drawdown**: Current equity drop from peak
- **Max Drawdown**: Largest drawdown experienced
- **Peak Balance**: Highest account equity reached
- **Drawdown Limit**: 12% limit for MICRO_CAP mode

Color coding:
- Green: Drawdown < 6%
- Yellow: Drawdown 6-10%
- Red: Drawdown > 10%

### 6. Compliance Alerts (⚠️)
Monitors and displays alerts for:
- Drawdown limit violations (>12%)
- Position limit violations (>2 positions)
- High exposure warnings (>40%)
- Minimum balance warnings (<$15)

Alert levels:
- ✅ Success: All systems operational
- ⚠️ Warning: Approaching limits
- 🚨 Error: Limit exceeded

### 7. Open Orders Table (📋)
Shows all active positions with:
- Symbol
- Side (BUY/SELL)
- Position size
- Entry price
- Current price
- P&L (dollar amount)
- P&L % (percentage)

## API Endpoints

### Get Complete Dashboard Data
```
GET /api/v1/dashboard/micro-cap
```

Returns all dashboard metrics in one response.

### Get Balances Only
```
GET /api/v1/dashboard/micro-cap/balances
```

Returns: `{cash, equity, available, reserved}`

### Get Held Capital Only
```
GET /api/v1/dashboard/micro-cap/held-capital
```

Returns: `{value, count, unrealized_pnl, exposure_pct}`

### Get Expectancy Metrics Only
```
GET /api/v1/dashboard/micro-cap/expectancy
```

Returns: `{win_rate, profit_factor, avg_win, avg_loss}`

### Get Drawdown Metrics Only
```
GET /api/v1/dashboard/micro-cap/drawdown
```

Returns: `{current, max, peak_balance}`

### Get Compliance Alerts Only
```
GET /api/v1/dashboard/micro-cap/compliance
```

Returns: Array of `{severity, message}` objects

### Health Check
```
GET /health
```

Returns: `{status, timestamp}`

## Configuration

### Environment Variables

- `DASHBOARD_PORT`: Port to run dashboard on (default: 5002)
- `FLASK_ENV`: Flask environment (default: production)

### MICRO_CAP Mode Requirements

The dashboard is designed for MICRO_CAP mode with these parameters:
- Minimum balance: $15
- Maximum positions: 2
- Maximum drawdown: 12%
- Reserved buffer: 15%
- Maximum exposure: 40% (warning threshold)

## Integration with NIJA Bot

The dashboard automatically integrates with:

1. **broker_integration**: For balance and position data
2. **kpi_tracker**: For expectancy and performance metrics
3. **risk_manager**: For drawdown calculations

If these components are not available, the dashboard falls back to mock data for testing purposes.

## Troubleshooting

### Dashboard shows mock data
**Cause**: Bot components not initialized or not running
**Solution**: Ensure NIJA bot is running with proper configuration

### Cannot connect to API
**Cause**: Dashboard server not running or port conflict
**Solution**: 
1. Check if server is running
2. Try a different port: `DASHBOARD_PORT=8080 ./start_micro_cap_dashboard.sh`

### Metrics not updating
**Cause**: Auto-refresh failed or connection lost
**Solution**: 
1. Check network connection indicator (red = disconnected)
2. Refresh the page manually
3. Check server logs for errors

### Compliance alerts not showing
**Cause**: All systems within normal parameters
**Solution**: This is normal - alerts only appear when limits are approached or exceeded

## Best Practices

### For the First 50 Trades

1. **Keep the dashboard open** during trading sessions
2. **Monitor compliance alerts** closely
3. **Watch drawdown** - stop trading if approaching 10%
4. **Track position limits** - never exceed 2 positions in MICRO_CAP mode
5. **Review expectancy** after every 5-10 trades
6. **Document issues** - take screenshots if you see unusual behavior

### Daily Checklist

Before each trading session:
- [ ] Start the dashboard
- [ ] Verify balance is above $15
- [ ] Confirm no compliance alerts
- [ ] Check current drawdown is acceptable
- [ ] Review recent trade expectancy

After each trading session:
- [ ] Review trade progress (X/50)
- [ ] Check final drawdown for the day
- [ ] Note any compliance issues
- [ ] Record key metrics for analysis

## Performance Targets

For successful MICRO_CAP operation (first 50 trades):

- **Win Rate**: Target 55-65%
- **Profit Factor**: Target >1.5
- **Max Drawdown**: Stay under 10%
- **Position Count**: Never exceed 2
- **Balance**: Maintain above $15

## Security Notes

- Dashboard runs on localhost by default (not exposed to internet)
- No authentication required for local access
- API provides read-only access to metrics
- No trading controls or order placement available through dashboard

## Support

For issues or questions:
1. Check server logs for error messages
2. Review MICRO_CAP configuration in `.env.micro_capital`
3. Consult main NIJA documentation
4. Verify bot is running in MICRO_CAP mode

## Version History

**v1.0** (February 17, 2026)
- Initial release
- Real-time monitoring for first 50 trades
- Compliance alert system
- Drawdown tracking
- Expectancy calculations
- Visual progress tracking

## License

Part of NIJA Trading Systems
© 2026 All Rights Reserved

## Related Documentation

- `MICRO_PLATFORM_GUIDE.md` - MICRO_CAP mode setup guide
- `MICRO_CAPITAL_AUTO_SCALING_GUIDE.md` - Auto-scaling documentation
- `.env.micro_capital` - MICRO_CAP environment configuration
- `IMPLEMENTATION_SUMMARY_MICRO_CAP.md` - MICRO_CAP implementation details
