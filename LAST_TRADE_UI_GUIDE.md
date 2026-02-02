# Last Evaluated Trade UI Panel & Dry-Run Simulator

This document describes the new features for UI transparency and App Store review mode.

## 🎯 Last Evaluated Trade UI Panel

### Overview

The bot now tracks the most recent trade signal evaluation and exposes it via API for UI display. This provides real-time transparency into what the bot is evaluating and why trades are (or aren't) being executed.

### What's Tracked

Every time the bot evaluates a potential trade, it records:

- **Timestamp**: When the signal was evaluated
- **Symbol**: Trading pair (e.g., BTC-USD, ETH-USD)
- **Signal**: BUY or SELL
- **Action**: 
  - `executed` - Trade was placed
  - `vetoed` - Trade was blocked (see veto_reasons)
  - `evaluated` - Signal was analyzed but not acted on
- **Veto Reasons**: List of why trade was blocked (if applicable)
- **Entry Price**: Proposed entry price
- **Position Size**: Proposed position size in USD
- **Broker**: Which broker would execute (KRAKEN, etc.)
- **Confidence**: Signal confidence score (0.0-1.0)
- **RSI Values**: Technical indicators (RSI 9 and RSI 14)

### API Endpoints

#### Get Last Evaluated Trade
```bash
GET http://localhost:5001/api/last-trade
```

**Response:**
```json
{
  "success": true,
  "data": {
    "timestamp": "2026-02-02T23:30:00",
    "symbol": "BTC-USD",
    "signal": "BUY",
    "action": "vetoed",
    "veto_reasons": [
      "Insufficient balance ($15.00 < $25.00)",
      "Position cap reached (7/7)"
    ],
    "entry_price": 42500.00,
    "position_size": 50.00,
    "broker": "KRAKEN",
    "confidence": 0.85,
    "rsi_9": 35.2,
    "rsi_14": 38.7
  }
}
```

#### Health Check
```bash
GET http://localhost:5001/api/health
```

**Response:**
```json
{
  "status": "healthy",
  "api": "last-trade",
  "strategy_registered": true
}
```

#### Dry-Run Status
```bash
GET http://localhost:5001/api/dry-run-status
```

**Response:**
```json
{
  "dry_run_mode": false,
  "message": "Live trading mode"
}
```

### Usage in Code

```python
# In bot/trading_strategy.py, the strategy instance tracks this automatically:

# When a trade is evaluated (successful or vetoed):
self._update_last_evaluated_trade(
    symbol='BTC-USD',
    signal='BUY',
    action='vetoed',
    veto_reasons=['Insufficient balance ($15.00 < $25.00)'],
    entry_price=42500.00,
    position_size=50.00,
    broker='KRAKEN',
    confidence=0.85,
    rsi_9=35.2,
    rsi_14=38.7
)

# To retrieve for display:
last_trade = strategy.get_last_evaluated_trade()
```

### Starting the API Server

The API server can be started in the bot initialization:

```python
from bot.last_trade_api import start_last_trade_api_server

# After strategy initialization:
start_last_trade_api_server(
    strategy=strategy_instance,
    port=5001,  # Optional, defaults to 5001
    background=True  # Run in background thread
)
```

Or set the port via environment variable:
```bash
LAST_TRADE_API_PORT=5001
```

## 🎭 Dry-Run Simulator Mode

### Overview

Dry-run mode allows the bot to evaluate signals and demonstrate trading logic **without placing real orders**. This is perfect for:

- **App Store Review**: Show functionality without risking real money
- **Testing**: Verify strategy logic safely
- **Demonstrations**: Showcase bot capabilities to potential users

### Enabling Dry-Run Mode

Set in environment variables:
```bash
DRY_RUN_MODE=true
```

Or in `.env` file:
```bash
# DRY-RUN SIMULATOR MODE - App Store Review Mode
DRY_RUN_MODE=true
```

### What Happens in Dry-Run Mode

1. **Normal Signal Evaluation**: Bot analyzes markets using live data
2. **Tracks Decisions**: Updates last evaluated trade with full details
3. **NO REAL ORDERS**: All trade executions are simulated
4. **Logs Everything**: Shows what *would* happen in live mode
5. **API Accessible**: UI can display simulated trades

### Startup Banner

When dry-run mode is active, you'll see:
```
======================================================================
🎭 DRY-RUN SIMULATOR MODE ACTIVE
======================================================================
   FOR APP STORE REVIEW ONLY
   All trades are simulated - NO REAL ORDERS PLACED
   Broker API calls return mock data
======================================================================
```

### Checking Dry-Run Status

Via API:
```bash
curl http://localhost:5001/api/dry-run-status
```

In logs:
```
🎭 DRY-RUN SIMULATOR MODE ACTIVE
```

## 📱 UI Integration Examples

### React Example

```javascript
import React, { useState, useEffect } from 'react';

function LastTradePanel() {
  const [trade, setTrade] = useState(null);
  
  useEffect(() => {
    const fetchTrade = async () => {
      const response = await fetch('http://localhost:5001/api/last-trade');
      const data = await response.json();
      if (data.success) {
        setTrade(data.data);
      }
    };
    
    // Fetch every 5 seconds
    const interval = setInterval(fetchTrade, 5000);
    fetchTrade(); // Initial fetch
    
    return () => clearInterval(interval);
  }, []);
  
  if (!trade) return <div>Loading...</div>;
  
  return (
    <div className="last-trade-panel">
      <h3>Last Evaluated Trade</h3>
      <div className="trade-info">
        <p><strong>Symbol:</strong> {trade.symbol}</p>
        <p><strong>Signal:</strong> {trade.signal}</p>
        <p><strong>Action:</strong> 
          <span className={trade.action === 'executed' ? 'success' : 'warning'}>
            {trade.action}
          </span>
        </p>
        {trade.veto_reasons.length > 0 && (
          <div className="veto-reasons">
            <strong>Veto Reasons:</strong>
            <ul>
              {trade.veto_reasons.map((reason, idx) => (
                <li key={idx}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
        <p><strong>Entry Price:</strong> ${trade.entry_price?.toFixed(2)}</p>
        <p><strong>Position Size:</strong> ${trade.position_size?.toFixed(2)}</p>
        <p><strong>Confidence:</strong> {(trade.confidence * 100)?.toFixed(1)}%</p>
        <p><strong>Time:</strong> {new Date(trade.timestamp).toLocaleString()}</p>
      </div>
    </div>
  );
}

export default LastTradePanel;
```

### Vue Example

```vue
<template>
  <div class="last-trade-panel">
    <h3>Last Evaluated Trade</h3>
    <div v-if="trade" class="trade-info">
      <p><strong>Symbol:</strong> {{ trade.symbol }}</p>
      <p><strong>Signal:</strong> {{ trade.signal }}</p>
      <p><strong>Action:</strong> 
        <span :class="trade.action === 'executed' ? 'success' : 'warning'">
          {{ trade.action }}
        </span>
      </p>
      <div v-if="trade.veto_reasons.length" class="veto-reasons">
        <strong>Veto Reasons:</strong>
        <ul>
          <li v-for="(reason, idx) in trade.veto_reasons" :key="idx">
            {{ reason }}
          </li>
        </ul>
      </div>
      <p><strong>Entry Price:</strong> ${{ trade.entry_price?.toFixed(2) }}</p>
      <p><strong>Position Size:</strong> ${{ trade.position_size?.toFixed(2) }}</p>
      <p><strong>Confidence:</strong> {{ (trade.confidence * 100)?.toFixed(1) }}%</p>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      trade: null,
      intervalId: null
    };
  },
  mounted() {
    this.fetchTrade();
    this.intervalId = setInterval(this.fetchTrade, 5000);
  },
  beforeUnmount() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
    }
  },
  methods: {
    async fetchTrade() {
      const response = await fetch('http://localhost:5001/api/last-trade');
      const data = await response.json();
      if (data.success) {
        this.trade = data.data;
      }
    }
  }
};
</script>
```

## 🔒 Security Considerations

### Production Deployment

1. **Enable CORS** if UI is on different domain:
   ```python
   from flask_cors import CORS
   CORS(app, origins=['https://your-ui-domain.com'])
   ```

2. **Add Authentication** for sensitive environments:
   ```python
   @app.before_request
   def check_auth():
       token = request.headers.get('Authorization')
       if not verify_token(token):
           return jsonify({'error': 'Unauthorized'}), 401
   ```

3. **Rate Limiting** to prevent abuse:
   ```python
   from flask_limiter import Limiter
   limiter = Limiter(app, default_limits=["100 per hour"])
   ```

## 📊 Monitoring & Debugging

### Check API is Running

```bash
curl http://localhost:5001/api/health
```

### View Latest Trade Data

```bash
curl http://localhost:5001/api/last-trade | jq
```

### Monitor in Real-Time

```bash
watch -n 5 'curl -s http://localhost:5001/api/last-trade | jq .data'
```

## 🚀 Deployment

### Railway

Add to environment variables:
```bash
LAST_TRADE_API_PORT=5001
DRY_RUN_MODE=false  # or true for review mode
```

### Docker

Expose the port in `Dockerfile`:
```dockerfile
EXPOSE 5001
```

And in `docker-compose.yml`:
```yaml
ports:
  - "5001:5001"
environment:
  - LAST_TRADE_API_PORT=5001
```

## ✅ Testing the API

Run the test server:
```bash
cd bot
python last_trade_api.py
```

Then test endpoints:
```bash
# Health check
curl http://localhost:5001/api/health

# Last trade
curl http://localhost:5001/api/last-trade

# Dry-run status
curl http://localhost:5001/api/dry-run-status
```

## 📝 Next Steps

1. Integrate the API into your UI/dashboard
2. Create UI panels to display last evaluated trade
3. Use dry-run mode for App Store review
4. Monitor trade decisions in real-time
5. Build analytics around veto reasons

**Pro Tip**: Combine the Last Trade API with dry-run mode to demonstrate bot functionality to App Store reviewers without risking real capital!
