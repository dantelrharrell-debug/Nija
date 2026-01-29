# TradingView Webhook Setup Guide

## 🎯 Overview

NIJA now supports **TradingView webhook alerts** for instant trade execution on Coinbase!

**Dual-Mode Trading:**
- ✅ **Autonomous Mode**: NIJA scans 732 markets every 2.5 minutes (continues running)
- ✅ **TradingView Webhooks**: Instant execution when your TradingView alerts fire

**NIJA Position Management Applied to Both:**
- 🔒 95% Profit Lock (never give back gains)
- 🔺 Pyramiding at +1%, +2%, +3%
- 💎 Extended runners to 20%
- ⚡ Partial exits at TP0.5/TP1/TP2

---

## 📡 Webhook URL

Once deployed on Render:
```
https://nija-trading-bot-v9xl.onrender.com/webhook
```

**Endpoints:**
- `POST /webhook` - Receive TradingView alerts
- `GET /health` - Health check
- `GET /positions` - View all open positions

---

## 🔐 Webhook Secret

Set in Railway environment variables:
```
TRADINGVIEW_WEBHOOK_SECRET=nija_webhook_2025
```

**Security:** Only alerts with matching secret will be executed.

---

## 📋 TradingView Alert Message Format

### **Single-Symbol Alert (Legacy):**
```json
{
  "secret": "nija_webhook_2025",
  "action": "buy",
  "symbol": "BTC-USD",
  "size": 10.0,
  "message": "Strong bullish setup detected"
}
```

### **Multi-Symbol Alert (NEW):**
```json
{
  "secret": "nija_webhook_2025",
  "orders": [
    {"action": "buy", "symbol": "BTC-USD", "size": 10.0},
    {"action": "sell", "symbol": "ETH-USD"},
    {"action": "buy", "symbol": "SOL-USD", "size": 5.0}
  ]
}
```

### **Field Descriptions:**

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `secret` | ✅ Yes | Webhook authentication | `"nija_webhook_2025"` |
| `action` | ✅ Yes (single) | Trade action | `"buy"` or `"sell"` |
| `orders` | ✅ Yes (multi) | List of order objects | See above |
| `symbol` | ✅ Yes | Coinbase product ID | `"BTC-USD"`, `"ETH-USD"` |
| `size` | ❌ No | USD position size | `10.0` (uses NIJA sizing if omitted) |
| `message` | ❌ No | Custom message | Any string |

**Symbol Format:**
- `BTC-USD` ✅ (preferred)
- `BTC` ✅ (auto-converts to BTC-USD)
- `BTCUSD` ❌ (invalid)

---

## 🎨 TradingView Alert Setup

### **1. Create Alert in TradingView:**

1. Open your chart with indicators
2. Click **Alert** button (⏰)
3. Set your condition (e.g., "RSI crosses above 70")
4. Name your alert
5. Set **Webhook URL** to your Railway deployment

### **2. Message Template:**

**For BUY alerts:**
```json
{
  "secret": "nija_webhook_2025",
  "action": "buy",
  "symbol": "{{ticker}}",
  "message": "TradingView alert: {{strategy.order.action}}"
}
```

**For SELL alerts:**
```json
{
  "secret": "nija_webhook_2025",
  "action": "sell",
  "symbol": "{{ticker}}",
  "message": "TradingView exit signal"
}
```

**TradingView Variables:**
- `{{ticker}}` - Automatically uses chart symbol
- `{{close}}` - Current price
- `{{strategy.order.action}}` - Strategy action (buy/sell)

### **3. Alert Settings:**
- **Condition**: Your indicator/strategy condition
- **Options**:
  - ✅ "Once Per Bar Close" (recommended)
  - ✅ "Webhook URL" enabled
- **Expiration**: Open-ended

---

## 🚀 Railway Deployment

### **Option 1: Dual-Mode (Recommended)**

Run both autonomous bot AND webhook service:

**Update `start.sh`:**
```bash
#!/bin/bash
python3 bot/start_webhook_service.py
```

**Or update Railway start command:**
```
python3 bot/start_webhook_service.py
```

### **Option 2: Webhook-Only Mode**

Run only TradingView webhooks (no autonomous scanning):

```bash
python3 bot/tradingview_webhook.py
```

---

## 🔧 Environment Variables

Set these in Railway:

```bash
COINBASE_API_KEY=your_key_here
COINBASE_API_SECRET=your_secret_here
TRADINGVIEW_WEBHOOK_SECRET=nija_webhook_2025
PORT=8080
```

---

## 📊 Example Workflow

**1. TradingView sends BUY alert:**
```json
{
  "secret": "nija_webhook_2025",
  "action": "buy",
  "symbol": "ETH-USD",
  "size": 25.0
}
```

**2. NIJA executes:**
- ✅ Validates webhook secret
- ✅ Fetches ETH-USD candles
- ✅ Places $25 market buy order on Coinbase
- ✅ Opens NIJA position with 95% profit lock
- ✅ Sets stop-loss at 0.5-0.7%
- ✅ Prepares pyramiding at +1%, +2%, +3%

**3. NIJA manages position:**
- At +0.25%: 95% profit lock activates
- At +0.4%: TP0.5 exits 30%
- At +0.8%: TP1 exits 30% more
- At +1%: Pyramids +25% to position
- At +1.5%: TP2 exits 20%
- Remaining 20% trails to 20% with 95% lock

**4. TradingView sends SELL alert (optional):**
```json
{
  "secret": "nija_webhook_2025",
  "action": "sell",
  "symbol": "ETH-USD"
}
```

NIJA closes entire position immediately.

---

## 🧪 Testing

### **Test with curl:**

```bash
curl -X POST https://your-nija-app.railway.app/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "nija_webhook_2025",
    "action": "buy",
    "symbol": "BTC-USD",
    "size": 5.0,
    "message": "Test alert"
  }'
```

**Expected response:**
```json
{
  "status": "success",
  "action": "buy",
  "symbol": "BTC-USD",
  "size": 5.0,
  "message": "Buy order executed for BTC-USD",
  "nija_features": [
    "95% profit lock at +0.25%",
    "Pyramiding at +1%, +2%, +3%",
    "Extended runners to 20%",
    "TP0.5/TP1/TP2 partial exits"
  ]
}
```

### **Check positions:**

```bash
curl https://your-nija-app.railway.app/positions
```

---

## 🎯 Use Cases

**1. Combine TradingView Indicators with NIJA Exits:**
- Use TradingView's advanced indicators for entries
- Let NIJA manage exits with 95% profit lock

**2. Multi-Strategy Trading:**
- Run multiple TradingView strategies simultaneously
- All managed by single NIJA instance

**3. Custom Alert Logic:**
- Build complex TradingView alerts with Pine Script
- Execute instantly on Coinbase via NIJA

**4. Hybrid Approach:**
- NIJA autonomous: Scans 732 markets for opportunities
- TradingView: Your custom setups on specific charts
- Both feed into same position management system

---

## 🔒 Security Best Practices

1. **Keep webhook secret private** - Don't share in public TradingView alerts
2. **Use HTTPS only** - Railway provides SSL by default
3. **Monitor webhook logs** - Check for unauthorized attempts
4. **Rotate secrets periodically** - Update in both TradingView and Railway

---

## 🐛 Troubleshooting

**"Unauthorized" error:**
- Check webhook secret matches in TradingView and Railway environment

**"Symbol not found":**
- Ensure symbol is valid Coinbase product (BTC-USD, ETH-USD, etc.)
- Check symbol format (use hyphen: BTC-USD not BTCUSD)

**"Position size too small":**
- Minimum is $0.005
- Increase `size` in alert or let NIJA calculate dynamically

**No response from webhook:**
- Check Railway logs for errors
- Verify webhook URL is correct
- Test with curl to isolate TradingView vs. NIJA issue

---

## 📈 Performance

**TradingView → NIJA → Coinbase:**
- Alert fires: **< 1 second**
- NIJA receives: **< 1 second**
- Order executed: **1-3 seconds**
- **Total latency: ~2-5 seconds**

---

## 🚀 Next Steps

1. Deploy updated NIJA with webhook support
2. Set `TRADINGVIEW_WEBHOOK_SECRET` in Railway
3. Create TradingView alerts with webhook URL
4. Test with small position sizes
5. Monitor Railway logs for webhook activity
6. Scale up once confirmed working

**Your TradingView strategies + NIJA position management = Unstoppable! 🎯**
