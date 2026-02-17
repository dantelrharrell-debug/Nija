# NIJA MICRO_CAP Production Readiness Dashboard - Quick Start

## What is this?

A one-page real-time dashboard for monitoring your first 50 trades in MICRO_CAP mode.

**Screenshot:**

![Dashboard](https://github.com/user-attachments/assets/e16de079-2089-4bc0-9aef-22f6bd97d92c)

## Quick Start (3 steps)

### 1. Start the Dashboard

```bash
./start_micro_cap_dashboard.sh
```

### 2. Open in Browser

Navigate to: **http://localhost:5002/dashboard**

### 3. Monitor Your Trades

The dashboard auto-refreshes every 5 seconds and shows:
- ✅ Real-time balances
- ✅ Open positions and P&L
- ✅ Win rate and expectancy
- ✅ Drawdown tracking
- ✅ Compliance alerts
- ✅ Progress toward 50 trades

## What You'll See

### 📊 Trade Progress
Visual progress bar showing X/50 trades completed

### 💰 Balances
- Cash Balance
- Account Equity
- Available Capital
- Reserved Buffer (15%)

### 🔒 Held Capital
- Positions Value
- Open Positions Count
- Unrealized P&L
- Exposure %

### 📈 Expectancy
- Win Rate %
- Profit Factor
- Average Win
- Average Loss

### 📉 Drawdown Tracker
- Current Drawdown (%)
- Max Drawdown (%)
- Peak Balance
- Drawdown Limit (12%)

### ⚠️ Compliance Alerts
Real-time warnings for:
- Drawdown limit violations (>12%)
- Position limit violations (>2 positions)
- High exposure warnings (>40%)
- Low balance warnings (<$15)

### 📋 Open Orders Table
Live view of all active positions with current prices and P&L

## Color Coding

- 🟢 **Green**: Good / Within limits
- 🟡 **Yellow**: Warning / Approaching limit
- 🔴 **Red**: Error / Limit exceeded

## Stopping the Dashboard

Press `Ctrl+C` in the terminal where it's running.

## Troubleshooting

**Dashboard not loading?**
- Check if server is running: `ps aux | grep micro_cap_dashboard`
- Try a different port: `DASHBOARD_PORT=8080 ./start_micro_cap_dashboard.sh`

**Shows mock data?**
- This is normal if the bot isn't running
- Start NIJA bot to see real data

**Connection lost?**
- Check the status indicator (should be green)
- Refresh the page
- Restart the dashboard server

## For More Information

See: `MICRO_CAP_DASHBOARD_README.md`
