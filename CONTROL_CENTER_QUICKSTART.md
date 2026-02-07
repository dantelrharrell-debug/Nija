# NIJA Control Center - Quick Start Guide

This is a 5-minute quick start guide to get the NIJA Control Center running.

## What is the Control Center?

The Control Center is your unified operational dashboard for monitoring and controlling NIJA trading bot. It provides:
- Real-time balances and positions across all users
- Trading status and alerts
- Quick action buttons (emergency stop, pause/resume)
- Both CLI and web interfaces

## Quick Start

### Option 1: CLI Dashboard (Recommended for SSH/Terminal)

```bash
# One-time snapshot (no loop)
python nija_control_center.py --snapshot

# Interactive dashboard with auto-refresh
python nija_control_center.py

# Custom refresh interval (5 seconds)
python nija_control_center.py --refresh-interval 5
```

**CLI Keyboard Commands:**
- `R` - Refresh now
- `E` - Emergency stop
- `P` - Pause trading
- `S` - Start trading
- `U` - User status
- `Q` - Quit

### Option 2: Web Dashboard (Recommended for Browser)

```bash
# Start the dashboard server
python bot/dashboard_server.py
```

Then open your browser to:
- **Control Center**: http://localhost:5001/control-center
- Main Dashboard: http://localhost:5001
- Users Dashboard: http://localhost:5001/users

The web dashboard auto-refreshes every 10 seconds.

### Option 3: Run the Demo

```bash
# See everything in action without a database
python demo_control_center.py
```

## What You'll See

### Platform Overview
- Total users and active users
- Trading status (enabled/disabled)
- Total capital across all accounts
- Open positions count
- Unrealized P&L
- Daily P&L

### User Status
Each user shows:
- Trading readiness (🟢 ready, 🔴 disabled)
- Balance and positions
- Unrealized P&L
- Risk level

### Alerts
- Recent system alerts
- Severity levels (error, warning, info)
- Timestamps

### Open Positions
- Symbol and side
- Size and prices
- Real-time P&L
- Broker info

## Quick Actions

### Emergency Stop
Immediately disables all trading across the platform.

**CLI:** Press `E`
**Web:** Click "Emergency Stop" button
**API:** `POST /api/control-center/actions/emergency-stop`

### Pause Trading
Temporarily suspends trading (can be resumed).

**CLI:** Press `P`
**Web:** Click "Pause Trading" button
**API:** `POST /api/control-center/actions/pause-trading`

### Resume Trading
Re-enables trading after pause.

**CLI:** Press `S`
**Web:** Click "Resume Trading" button
**API:** `POST /api/control-center/actions/resume-trading`

## API Usage

The Control Center provides a RESTful API:

```bash
# Check system health
curl http://localhost:5001/api/control-center/health

# Get platform overview
curl http://localhost:5001/api/control-center/overview

# Get all users
curl http://localhost:5001/api/control-center/users

# Get open positions
curl http://localhost:5001/api/control-center/positions

# Get recent alerts
curl http://localhost:5001/api/control-center/alerts

# Emergency stop (requires POST)
curl -X POST http://localhost:5001/api/control-center/actions/emergency-stop
```

## Troubleshooting

### "No users found"
This is normal if:
- Database is not initialized
- No users have been created yet
- Running in demo mode

### "Database not available"
The Control Center works without a database but shows limited data. To fix:
1. Ensure database is running
2. Run `python init_database.py` to initialize

### "Controls not available"
Some features require the controls module. Check that:
- `controls.py` exists and is accessible
- Hard controls are properly configured

### Web dashboard not loading
1. Check Flask server is running
2. Verify port 5001 is accessible
3. Check browser console for errors

## Next Steps

- Read [CONTROL_CENTER.md](CONTROL_CENTER.md) for complete documentation
- Explore the web dashboard features
- Set up custom alerts
- Integrate with your monitoring tools

## Need Help?

- Check the main [README.md](README.md)
- Review [CONTROL_CENTER.md](CONTROL_CENTER.md) for detailed docs
- Run `python demo_control_center.py` for a guided tour
- Check system logs for errors

---

**Version:** 1.0  
**Date:** February 7, 2026  
**Author:** NIJA Trading Systems
