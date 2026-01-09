# NIJA Active Trading Status - Complete Guide

**Last Updated:** January 9, 2026  
**Version:** 1.0

---

## Quick Answer: Is NIJA Trading for Me and Other Users?

### Three Ways to Check

#### 1. **Via Web Browser** (Easiest) 🌐

Visit the status page when the bot is running:

```
http://localhost:5001/status
```

Or on your deployment:
```
https://your-app.railway.app/status
```

**What you'll see:**
- 🟢 **ACTIVE** - NIJA is actively trading with open positions
- 🟡 **READY** - NIJA is running and monitoring, waiting for signals
- 🔴 **STOPPED** - NIJA bot is not running

The page auto-refreshes every 10 seconds.

---

#### 2. **Via API** (For Developers) 🔧

```bash
curl http://localhost:5001/api/trading_status
```

Or on your deployment:
```bash
curl https://your-app.railway.app/api/trading_status
```

**Response:**
```json
{
  "timestamp": "2026-01-09T04:57:00.000Z",
  "is_trading": true,
  "trading_status": "ACTIVE",
  "message": "NIJA is actively trading with 5 open positions across 2 broker(s)",
  "bot_running": true,
  "total_positions": 5,
  "trading_balance": 157.42,
  "active_brokers": [
    {
      "name": "Coinbase Advanced Trade",
      "positions": 3,
      "balance": 100.00
    },
    {
      "name": "Kraken Pro",
      "positions": 2,
      "balance": 57.42
    }
  ],
  "recent_activity": {
    "trades_24h": 12,
    "last_trade_time": "2026-01-09T04:45:00.000Z"
  },
  "users": [
    {
      "user_id": "daivon_frazier",
      "email": "frazierdaivon@gmail.com",
      "enabled": true,
      "can_trade": true,
      "tier": "Pro"
    }
  ]
}
```

---

#### 3. **Via Python Script** (Local Check) 🐍

```bash
python check_trading_status.py
```

**Output:**
```
================================================================================
NIJA ACTIVE TRADING STATUS CHECK
Timestamp: 2026-01-09 04:57:00 UTC
================================================================================

--------------------------------------------------------------------------------
CHECK 1: Bot Process Activity
--------------------------------------------------------------------------------
✅ Bot is RUNNING
   Log file: /usr/src/app/nija.log
   Last update: 2026-01-09 04:56:45
   Age: 15 seconds

--------------------------------------------------------------------------------
CHECK 2: Broker Positions & Balances
--------------------------------------------------------------------------------

📊 Total Open Positions: 5
💰 Total Trading Balance: $157.42

🔗 Connected Brokers:

   🟢 Coinbase Advanced Trade
      Positions: 3
      Balance: $100.00
      Status: ACTIVELY TRADING

   🟢 Kraken Pro
      Positions: 2
      Balance: $57.42
      Status: ACTIVELY TRADING

--------------------------------------------------------------------------------
CHECK 3: Recent Trading Activity
--------------------------------------------------------------------------------

📈 Trades (Last 24 Hours): 12
⏱️  Last Trade: 2026-01-09 04:45:00
   Time since last trade: 12 minutes ago

✅ Bot has been trading recently

--------------------------------------------------------------------------------
CHECK 4: User Trading Status
--------------------------------------------------------------------------------

👥 Configured Users: 1

✅ User: daivon_frazier
   Email: frazierdaivon@gmail.com
   Tier: Pro
   Enabled: True
   Can Trade: True

================================================================================
FINAL ASSESSMENT
================================================================================

🟢 CONCLUSION: NIJA IS ACTIVELY TRADING

✅ Evidence:
   • Bot process is running
   • 5 open positions
   • $157.42 available for trading
   • 12 trades in last 24 hours
   • Trading on: Coinbase Advanced Trade, Kraken Pro
```

---

## Trading Status Levels Explained

### 🟢 ACTIVE - Actively Trading

**What it means:**
- Bot is running
- Has open positions
- Actively managing trades
- Recent trading activity detected

**Indicators:**
- ✅ Open positions > 0
- ✅ Recent trades in last 24 hours
- ✅ Bot log file being updated

**What to expect:**
- Positions will be opened and closed based on strategy
- Trades every 2.5 minutes (market scanning cycle)
- Stop losses and profit targets managed automatically

---

### 🟡 READY - Running but Not Trading

**What it means:**
- Bot is running correctly
- Monitoring markets every 2.5 minutes
- No positions currently open
- Waiting for entry signals

**Indicators:**
- ✅ Bot log file being updated
- ❌ No open positions
- ℹ️  May have recent trades (all closed)

**Why this happens:**
- Strategy requires specific RSI conditions (RSI_9 < 35 or RSI_14 < 40)
- Market conditions don't meet entry criteria
- All recent positions were closed for profit/stop
- Bot just started and hasn't found signals yet

**This is normal!** The strategy is selective and only enters high-quality trades.

---

### 🔴 STOPPED - Not Running

**What it means:**
- Bot process is not running
- No trading activity
- Log file not being updated

**Indicators:**
- ❌ Log file last updated > 5 minutes ago
- ❌ No open positions
- ❌ No recent trading activity

**Common reasons:**
1. Deployment stopped or crashed
2. Insufficient balance (< $25 required)
3. API credentials invalid or missing
4. Manual shutdown
5. Error during startup

**What to do:**
1. Check deployment status (Railway/Render)
2. Check logs for errors
3. Verify balance on broker
4. Check API credentials in .env
5. Restart the bot

---

## Understanding the Status Fields

### Core Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `is_trading` | boolean | `true` if actively trading (has positions or recent trades) |
| `trading_status` | string | "ACTIVE", "READY", or "STOPPED" |
| `bot_running` | boolean | `true` if bot process is active (log updated < 5 min) |
| `message` | string | Human-readable status message |

### Position & Balance

| Field | Type | Description |
|-------|------|-------------|
| `total_positions` | number | Total open positions across all brokers |
| `trading_balance` | number | Total USD/USDC available for trading |
| `active_brokers` | array | List of connected brokers with positions/balance |

### Activity Tracking

| Field | Type | Description |
|-------|------|-------------|
| `recent_activity.trades_24h` | number | Number of trades in last 24 hours |
| `recent_activity.last_trade_time` | string | ISO timestamp of most recent trade |

### Multi-User Support

| Field | Type | Description |
|-------|------|-------------|
| `users` | array/null | List of users (if multi-user system active) |
| `users[].user_id` | string | User identifier |
| `users[].can_trade` | boolean | Whether user is authorized to trade |
| `users[].enabled` | boolean | Whether user account is enabled |

---

## Accessing Status Endpoints

### HTTP Endpoints

The bot exposes these endpoints when running:

#### 1. Human-Readable Status Page
```
GET http://localhost:5001/status
```
- Auto-refreshing HTML page
- Color-coded status indicator
- Shows all key metrics
- Updates every 10 seconds

#### 2. JSON API Endpoint
```
GET http://localhost:5001/api/trading_status
```
- Complete status information
- Suitable for monitoring tools
- Machine-readable JSON

#### 3. Simple Health Check
```
GET http://localhost:5001/health
```
- Returns: "OK" (200) if server is running
- Useful for uptime monitoring

### Production URLs

Replace `localhost:5001` with your deployment URL:

**Railway:**
```
https://your-app.railway.app/status
https://your-app.railway.app/api/trading_status
```

**Render:**
```
https://your-app.onrender.com/status
https://your-app.onrender.com/api/trading_status
```

---

## Integration Examples

### Shell Script

```bash
#!/bin/bash
# Check if NIJA is trading

response=$(curl -s http://localhost:5001/api/trading_status)
status=$(echo $response | jq -r '.trading_status')

if [ "$status" = "ACTIVE" ]; then
    echo "✅ NIJA is actively trading"
    exit 0
elif [ "$status" = "READY" ]; then
    echo "🟡 NIJA is ready but waiting for signals"
    exit 0
else
    echo "🔴 NIJA is not running"
    exit 1
fi
```

### Python Monitoring

```python
import requests
import time

def monitor_trading_status():
    """Monitor NIJA trading status continuously"""
    while True:
        try:
            response = requests.get('http://localhost:5001/api/trading_status')
            data = response.json()
            
            status = data.get('trading_status')
            positions = data.get('total_positions', 0)
            balance = data.get('trading_balance', 0)
            
            print(f"[{datetime.now()}] Status: {status} | "
                  f"Positions: {positions} | Balance: ${balance:.2f}")
            
            # Alert if stopped
            if status == 'STOPPED':
                send_alert("NIJA bot has stopped!")
            
        except Exception as e:
            print(f"Error checking status: {e}")
        
        time.sleep(60)  # Check every minute

monitor_trading_status()
```

### JavaScript/Node.js

```javascript
const axios = require('axios');

async function checkTradingStatus() {
  try {
    const response = await axios.get('http://localhost:5001/api/trading_status');
    const { trading_status, total_positions, trading_balance } = response.data;
    
    console.log(`Status: ${trading_status}`);
    console.log(`Positions: ${total_positions}`);
    console.log(`Balance: $${trading_balance.toFixed(2)}`);
    
    return trading_status === 'ACTIVE';
  } catch (error) {
    console.error('Error checking status:', error.message);
    return false;
  }
}

// Check every 5 minutes
setInterval(checkTradingStatus, 5 * 60 * 1000);
```

---

## Troubleshooting

### Issue: Endpoints Not Responding

**Problem:** Can't access http://localhost:5001/status

**Solutions:**
1. Check if dashboard server is running:
   ```bash
   ps aux | grep dashboard_server
   ```

2. Start the dashboard server:
   ```bash
   cd bot
   python dashboard_server.py
   ```

3. Check if port 5001 is in use:
   ```bash
   lsof -i :5001
   ```

---

### Issue: Shows "STOPPED" but Bot is Running

**Problem:** Status shows STOPPED even though bot appears to be running

**Solutions:**
1. Check log file location - may be in different directory
2. Verify log file is being written to:
   ```bash
   ls -lh nija.log
   stat nija.log
   ```

3. Check if bot is actually running:
   ```bash
   ps aux | grep bot.py
   ps aux | grep trading_strategy
   ```

---

### Issue: No Broker Data

**Problem:** `active_brokers` is empty even with valid credentials

**Solutions:**
1. Verify credentials in .env file:
   ```bash
   grep COINBASE .env
   ```

2. Test connection manually:
   ```bash
   python check_broker_status.py
   ```

3. Check for import errors in logs

---

### Issue: Users Array is `null`

**Problem:** `users` field is `null` in response

**This is expected!** The multi-user system is optional.

- `users: null` means multi-user system is not initialized
- Bot still works with direct broker credentials
- To enable multi-user system:
  ```bash
  python init_user_system.py
  python setup_user_daivon.py
  ```

---

## Starting the Dashboard Server

The dashboard server needs to be running to access HTTP endpoints.

### Manual Start

```bash
cd bot
python dashboard_server.py
```

**Output:**
```
🚀 Starting NIJA Dashboard Server...
📊 Dashboard will be available at: http://localhost:5001
🔄 Auto-refresh every 5 seconds

Press Ctrl+C to stop

 * Running on http://0.0.0.0:5001
```

### Auto-Start with Bot

To start dashboard server automatically with the bot, add to `start.sh`:

```bash
# Start dashboard server in background
python bot/dashboard_server.py &
DASHBOARD_PID=$!

# Start main bot
python bot.py

# Cleanup on exit
kill $DASHBOARD_PID
```

### Docker/Container

If running in Docker, expose port 5001:

```dockerfile
EXPOSE 5001
```

```yaml
# docker-compose.yml
ports:
  - "5001:5001"
```

---

## Best Practices

### Monitoring

1. **Check status before making changes**
   ```bash
   python check_trading_status.py
   ```

2. **Monitor continuously in production**
   - Set up health check endpoint monitoring
   - Alert if status changes to STOPPED
   - Track position count over time

3. **Log status checks**
   ```bash
   python check_trading_status.py >> status_log.txt
   ```

### Security

1. **Don't expose dashboard publicly without authentication**
   - Dashboard shows sensitive trading data
   - Use reverse proxy with auth if needed
   - Or keep on localhost only

2. **Rate limit status endpoint**
   - Prevent abuse if exposed publicly
   - Implement caching if high traffic

3. **Sanitize error messages**
   - Don't expose API keys in errors
   - Already implemented in endpoints

---

## Related Documentation

- **[IS_NIJA_TRADING_NOW.md](IS_NIJA_TRADING_NOW.md)** - Original status guide
- **[ACTIVE_TRADING_STATUS_PER_BROKER.md](ACTIVE_TRADING_STATUS_PER_BROKER.md)** - Per-broker status
- **[HOW_NIJA_WORKS_NOW.md](HOW_NIJA_WORKS_NOW.md)** - System overview
- **[TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md)** - Common issues

---

## Summary

**Three ways to check if NIJA is trading:**

1. **Web Browser:** http://localhost:5001/status (easiest)
2. **API:** `curl http://localhost:5001/api/trading_status` (automation)
3. **Script:** `python check_trading_status.py` (comprehensive)

**Status levels:**
- 🟢 **ACTIVE** - Trading with open positions
- 🟡 **READY** - Running, waiting for signals (normal)
- 🔴 **STOPPED** - Not running (needs attention)

**Quick health check:**
```bash
curl http://localhost:5001/health
# Should return: OK
```

---

*Documentation created: January 9, 2026*  
*For support, see: TROUBLESHOOTING_GUIDE.md*
