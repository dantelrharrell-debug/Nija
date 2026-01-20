# NIJA User Dashboard Guide

## Overview

The NIJA User Dashboard provides real-time visibility into user account balances, trades, and trading performance. It displays information for all configured user accounts across multiple exchanges (Kraken, Alpaca, Coinbase).

## Starting the Dashboard

### Method 1: Using the dashboard server script

```bash
cd /path/to/Nija
python3 bot/dashboard_server.py
```

The dashboard will start on `http://localhost:5001`

### Method 2: Using the start script

```bash
python3 start_user_dashboard.py
```

## Available Endpoints

### 1. `/status` - Human-Readable Status Page

**URL**: `http://localhost:5001/status`

**Description**: Main dashboard page showing overall NIJA bot status and detailed user account information.

**Features**:
- Overall bot status (ACTIVE, READY, or STOPPED)
- Trading metrics (positions, balance, recent activity)
- **User Accounts Section** displaying:
  - User name and account details
  - Current account balance
  - Open positions count
  - Trading statistics (total trades, win rate)
  - Profit & Loss (total and daily)
  - Recent trades (if available)

**Auto-refresh**: Page refreshes every 10 seconds automatically.

**Screenshot Example**:

![NIJA User Dashboard](https://github.com/user-attachments/assets/cd966b00-2200-447e-b663-eb6d6aea9791)

The dashboard displays:
- Overall bot status (STOPPED/READY/ACTIVE)
- Trading metrics summary
- **User Accounts Section** with detailed cards for each user:
  - ✅ Daivon Frazier (Kraken)
  - ✅ Tania Gilbert (Kraken)
  - ✅ Tania Gilbert (Alpaca)
  
Each user card shows:
- Account balance
- Open positions count
- Total trades
- Win rate
- Total P&L (profit/loss)
- Daily P&L

### 2. `/api/users` - User List API

**URL**: `http://localhost:5001/api/users`

**Method**: GET

**Description**: Returns JSON data for all configured users with their account information.

**Response Format**:
```json
{
  "users": [
    {
      "user_id": "daivon_frazier",
      "name": "Daivon Frazier",
      "enabled": true,
      "account_type": "retail",
      "broker_type": "kraken",
      "balance": 1234.56,
      "positions_count": 2,
      "positions": [...],
      "total_pnl": 234.56,
      "daily_pnl": 12.34,
      "win_rate": 67.5,
      "total_trades": 45,
      "recent_trades": [
        {
          "symbol": "BTC-USD",
          "side": "buy",
          "quantity": 0.01,
          "price": 45000.00,
          "size_usd": 450.00,
          "pnl_usd": 12.34,
          "pnl_pct": 2.74,
          "timestamp": "2026-01-20T12:00:00",
          "broker": "kraken"
        }
      ]
    }
  ],
  "total_users": 1,
  "timestamp": "2026-01-20T18:00:00"
}
```

**Example Usage**:
```bash
curl http://localhost:5001/api/users | jq .
```

### 3. `/api/trading_status` - Comprehensive Trading Status

**URL**: `http://localhost:5001/api/trading_status`

**Method**: GET

**Description**: Returns comprehensive trading status including bot status, brokers, and user accounts.

**Response Format**:
```json
{
  "timestamp": "2026-01-20T18:00:00",
  "is_trading": true,
  "bot_running": true,
  "active_brokers": [
    {
      "name": "Kraken Pro",
      "positions": 2,
      "balance": 1500.00
    }
  ],
  "total_positions": 2,
  "trading_balance": 1500.00,
  "recent_activity": {
    "trades_24h": 5,
    "last_trade_time": "2026-01-20T17:30:00"
  },
  "bot_status": "running",
  "users": [
    {
      "user_id": "daivon_frazier",
      "name": "Daivon Frazier",
      "balance": 1234.56,
      "positions": 2,
      "total_pnl": 234.56,
      "daily_pnl": 12.34,
      "win_rate": 67.5,
      "total_trades": 45,
      "recent_trades": [...]
    }
  ],
  "trading_status": "ACTIVE",
  "message": "NIJA is actively trading with 2 open positions"
}
```

### 4. `/health` - Health Check

**URL**: `http://localhost:5001/health`

**Method**: GET

**Description**: Simple health check endpoint.

**Response**: `OK` (200 status code)

## User Configuration

Users are configured in JSON files located at `config/users/`:

- `retail_kraken.json` - Retail users on Kraken
- `retail_alpaca.json` - Retail users on Alpaca
- `retail_coinbase.json` - Retail users on Coinbase
- `investor_kraken.json` - Investor accounts on Kraken
- `investor_alpaca.json` - Investor accounts on Alpaca
- `investor_coinbase.json` - Investor accounts on Coinbase

**Example user configuration**:
```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  }
]
```

API credentials are configured in the `.env` file using the format:
```
KRAKEN_USER_DAIVON_API_KEY=your_api_key_here
KRAKEN_USER_DAIVON_API_SECRET=your_api_secret_here
```

## Viewing Account Balances and Trades

### When the bot is not running:

The dashboard will show:
- User accounts with $0.00 balances (credentials not connected)
- "STOPPED" status
- Empty trading activity

### When the bot is running and connected:

The dashboard will show:
- **Real account balances** from connected exchanges
- **Open positions** for each user
- **Trading statistics** (total trades, win rate, P&L)
- **Recent trades** with details
- "ACTIVE" or "READY" status

## Troubleshooting

### Users not appearing

1. Check that users are configured in `config/users/*.json`
2. Verify user configurations have the correct format
3. Check dashboard logs for errors

### Balances showing $0.00

1. Verify API credentials are set in `.env` file
2. Ensure the NIJA bot is running and connected to exchanges
3. Check that user credentials match the format in `.env.example`

### Dashboard not starting

1. Ensure Flask is installed: `pip install Flask==2.3.3`
2. Check that you're running from the repository root directory
3. Review the dashboard logs for import errors

## Security Notes

- The dashboard runs on localhost by default (not accessible from outside)
- API keys are never displayed in the dashboard
- User data is fetched in real-time from exchange APIs
- No sensitive information is stored by the dashboard

## Next Steps

For more detailed user management features, see:
- `USER_SETUP_GUIDE.md` - How to add/remove users
- `BROKER_INTEGRATION_GUIDE.md` - How to connect exchanges
- `USER_MANAGEMENT_FEATURES.md` - Advanced user management

## Support

If you encounter issues:
1. Check the dashboard logs: `/tmp/dashboard.log`
2. Review the main bot logs for connection errors
3. Verify all dependencies are installed: `pip install -r requirements.txt`
