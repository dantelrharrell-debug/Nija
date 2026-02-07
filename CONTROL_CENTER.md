# NIJA Control Center

The **NIJA Control Center** is a unified operational dashboard that provides comprehensive monitoring and control of the NIJA trading bot. It offers both a CLI launcher and a web-based dashboard for maximum flexibility.

## Overview

The Control Center consolidates all NIJA data, alerts, balances, and actions into a single interface, making it the operational command center for managing your trading infrastructure.

## Features

### 📊 Live Data & Monitoring
- **Real-time balances** across all users and brokers
- **Open positions** with P&L tracking
- **Performance metrics** and snapshots
- **User status** including trading readiness and risk levels
- **System health** monitoring (database, services, components)

### 🚨 Alerts & Notifications
- **Real-time alerts** for critical events
- **Alert history** with severity levels
- **Acknowledgment system** to track handled alerts
- **Visual indicators** for different alert types

### ⚡ Quick Actions
- **Emergency Stop** - Immediately disable all trading
- **Pause Trading** - Temporarily suspend trading activities
- **Resume Trading** - Re-enable trading after pause
- **Refresh Data** - Force immediate data update
- **User Management** - View detailed user status

### 📈 Snapshot Capabilities
- **Historical data** viewing
- **Performance reports** generation
- **Trade ledger** access
- **P&L tracking** over time

## Installation

The Control Center is already included in your NIJA installation. No additional dependencies are required.

## Usage

### CLI Control Center

The CLI provides an interactive terminal-based dashboard with auto-refresh capabilities.

#### Basic Usage

```bash
# Start the interactive CLI dashboard
python nija_control_center.py

# Custom refresh interval (5 seconds)
python nija_control_center.py --refresh-interval 5

# Show detailed information
python nija_control_center.py --detailed

# One-time snapshot (no loop)
python nija_control_center.py --snapshot
```

#### CLI Features

The CLI dashboard displays:
- **Platform Overview** - Total users, capital, positions, P&L
- **User Status** - Individual user balances and trading status
- **Recent Alerts** - Latest system alerts and warnings
- **Quick Action Menu** - Interactive command menu

#### CLI Keyboard Commands

While the dashboard is running:
- `R` - Refresh data now
- `E` - Emergency stop (disable all trading)
- `P` - Pause trading
- `S` - Start/resume trading
- `U` - Show detailed user status
- `Q` - Quit

#### CLI Output Example

```
====================================================================================================
NIJA CONTROL CENTER - Live Trading Dashboard
====================================================================================================
Last Updated: 2026-02-07 14:30:15

📊 PLATFORM OVERVIEW
----------------------------------------------------------------------------------------------------
  Total Users: 5 | Active: 4 | Trading: 🟢 ENABLED
  Database: ✅ Healthy
  Total Positions: 12
  Unrealized P&L: +$1,234.56

👥 USER STATUS
----------------------------------------------------------------------------------------------------
  ✅ 🟢 📈 john_doe (pro)
      Balance: $25,000.00 | Positions: 4 | P&L: +$456.78
  
  ✅ 🟢 📈 jane_smith (investor)
      Balance: $50,000.00 | Positions: 5 | P&L: +$789.01

🚨 RECENT ALERTS
----------------------------------------------------------------------------------------------------
  [INFO] 14:25:10 - Trading resumed
  [WARNING] 14:15:32 - High volatility detected on BTC-USD

⚡ QUICK ACTIONS
----------------------------------------------------------------------------------------------------
  [R] Refresh Now    [E] Emergency Stop    [P] Pause Trading
  [S] Start Trading  [U] User Status       [Q] Quit
----------------------------------------------------------------------------------------------------

Auto-refresh: 10s | Press a key for action or wait for auto-refresh...
```

### Web Dashboard

The web dashboard provides a modern, responsive interface accessible from any browser.

#### Starting the Dashboard

```bash
# Start the dashboard server (includes Control Center)
python bot/dashboard_server.py
```

The server will start on port 5001. You can then access:
- Control Center: http://localhost:5001/control-center
- Main Dashboard: http://localhost:5001
- Users Dashboard: http://localhost:5001/users
- Command Center: http://localhost:5001/command-center

#### Web Dashboard Features

The web dashboard displays:

1. **Platform Overview Card**
   - Total users and active users
   - Trading status (enabled/disabled)
   - Total capital across all accounts
   - Open positions count
   - Unrealized P&L
   - Daily P&L

2. **Quick Actions Card**
   - Resume Trading button
   - Pause Trading button
   - Emergency Stop button
   - Refresh Now button

3. **System Health Card**
   - Database status
   - Controls system status
   - Risk Manager status
   - Overall system health

4. **Active Users Panel**
   - User cards with status indicators
   - Balance per user
   - Position counts
   - P&L tracking
   - Trading readiness status

5. **Recent Alerts Panel**
   - Alert severity levels (error, warning, info)
   - Timestamps
   - Alert messages
   - Color-coded by severity

6. **Open Positions Table**
   - Symbol and side
   - Position size
   - Entry and current prices
   - Unrealized P&L
   - Broker information

#### Auto-Refresh

The web dashboard automatically refreshes every 10 seconds to display the latest data. You can also click "Refresh Now" for immediate updates.

## API Endpoints

The Control Center provides a RESTful API for programmatic access:

### Overview
- `GET /api/control-center/overview` - Platform overview
- `GET /api/control-center/health` - System health check

### Users
- `GET /api/control-center/users` - All user summaries

### Positions & Trades
- `GET /api/control-center/positions` - Open positions
- `GET /api/control-center/trades/recent?limit=50` - Recent trades

### Alerts
- `GET /api/control-center/alerts?limit=50` - Get alerts
- `POST /api/control-center/alerts` - Add new alert
- `POST /api/control-center/alerts/{id}/acknowledge` - Acknowledge alert
- `POST /api/control-center/alerts/clear` - Clear all alerts

### Actions
- `POST /api/control-center/actions/emergency-stop` - Emergency stop
- `POST /api/control-center/actions/pause-trading` - Pause trading
- `POST /api/control-center/actions/resume-trading` - Resume trading

### Metrics
- `GET /api/control-center/metrics` - Performance metrics

### API Response Format

All API endpoints return JSON in this format:

```json
{
  "success": true,
  "data": { ... },
  "timestamp": "2026-02-07T14:30:15.123Z"
}
```

Error responses:

```json
{
  "success": false,
  "error": "Error message here"
}
```

## Integration with Existing Tools

The Control Center integrates seamlessly with existing NIJA tools:

- **User Status Summary** (`user_status_summary.py`) - Called via CLI menu
- **Command Center Metrics** - Embedded in web dashboard
- **Database Models** - Uses existing Position, User, Trade models
- **Controls System** - Directly interfaces with hard controls
- **Risk Manager** - Displays risk status per user
- **PnL Tracker** - Shows real-time balance and P&L data

## Architecture

### CLI Component
- `nija_control_center.py` - Main CLI application
- Real-time data fetching from database
- Interactive menu system
- Auto-refresh loop

### API Component
- `control_center_api.py` - Flask API server
- RESTful endpoints for all operations
- State management for alerts
- Action execution endpoints

### Web Component
- `bot/templates/control_center.html` - Single-page dashboard
- Auto-refresh with JavaScript
- Responsive design
- Real-time action buttons

## Security Considerations

### Access Control
- The Control Center has full access to trading controls
- Ensure the dashboard is not exposed to the public internet
- Use firewall rules to restrict access to port 5001
- Consider adding authentication if deploying in production

### Emergency Actions
- Emergency Stop immediately disables all trading
- Actions are logged to the alert system
- All actions require confirmation in the web UI

## Troubleshooting

### CLI Not Showing Data

If the CLI shows "No users found" or empty data:
1. Check database connection: `python -c "from database.db_connection import check_database_health; print(check_database_health())"`
2. Verify database is initialized: `python init_database.py`
3. Check user records exist in database

### Web Dashboard Not Loading

If the web dashboard shows errors:
1. Check the Flask server is running: `python bot/dashboard_server.py`
2. Verify port 5001 is not in use: `lsof -i :5001` (Unix) or `netstat -ano | findstr :5001` (Windows)
3. Check browser console for JavaScript errors
4. Verify API endpoints are accessible: `curl http://localhost:5001/api/control-center/health`

### Action Buttons Not Working

If quick action buttons don't work:
1. Verify controls are available: Check logs for "Controls not available" warning
2. Ensure you have proper permissions
3. Check alert system is working
4. Review server logs for errors

### Auto-Refresh Not Working

If data doesn't auto-refresh:
1. Check browser JavaScript console for errors
2. Verify API endpoints are responding
3. Check network tab in browser dev tools
4. Try manual refresh button

## Performance Considerations

### CLI Performance
- Default refresh interval is 10 seconds
- Reduce interval for more frequent updates (minimum 5 seconds recommended)
- Increase interval to reduce database load

### Web Dashboard Performance
- Auto-refresh interval is 10 seconds
- Each refresh makes 5 API calls
- Designed to handle 100+ users efficiently
- Large position lists may need pagination in future

### Database Load
- Each refresh queries Users, Positions, and Trades tables
- Queries are optimized with filters and limits
- Consider adding indices if performance degrades with scale

## Future Enhancements

Potential future additions:
- WebSocket support for real-time updates without polling
- Advanced filtering and search
- Historical charts and graphs
- Export functionality for reports
- Mobile app integration
- Multi-user access control
- Custom alert rules
- Position management (close, modify stops)
- Trade execution from dashboard

## Support

For issues or questions:
1. Check the logs: CLI outputs to console, web server logs to standard output
2. Review error messages in browser console (F12)
3. Check database connectivity
4. Verify all required modules are imported successfully

## Related Documentation

- [README.md](README.md) - Main NIJA documentation
- [USER_MANAGEMENT.md](USER_MANAGEMENT.md) - User management system
- [COMMAND_CENTER_README.md](COMMAND_CENTER_README.md) - Command Center metrics
- [KPI_DASHBOARD.md](KPI_DASHBOARD.md) - KPI dashboard details

## Version History

- **v1.0** (February 7, 2026)
  - Initial release
  - CLI interactive dashboard
  - Web-based control center
  - RESTful API
  - Quick action buttons
  - Real-time monitoring
  - Alert management
