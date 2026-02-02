# 🚀 Quick Reference Card - NIJA Trading Bot Features

## 🔧 Railway Environment Variables (Required)

```bash
# Kraken Platform Credentials (REQUIRED)
KRAKEN_PLATFORM_API_KEY=<your-key>
KRAKEN_PLATFORM_API_SECRET=<your-secret>

# Safety & Mode
LIVE_CAPITAL_VERIFIED=true    # Enable live trading
HEARTBEAT_TRADE=false          # true = run 1 test trade then exit
DRY_RUN_MODE=false             # true = simulate trades (App Store mode)

# Optional
LAST_TRADE_API_PORT=5001       # API server port for UI panel
```

---

## 💓 Heartbeat Trade Verification

**Purpose:** Verify API credentials work end-to-end

### Steps:
1. Set `HEARTBEAT_TRADE=true` in Railway
2. Deploy
3. Check logs for:
   ```
   💓 HEARTBEAT TRADE VERIFICATION: ✅ SUCCESS
   ```
4. Set `HEARTBEAT_TRADE=false`
5. Redeploy

**What it does:** Buys $5-10 position → Immediately sells → Shuts down

---

## 🧠 Trust Layer Features

### 1. User Status Banner (Shows on Startup)
```
🧠 TRUST LAYER - USER STATUS BANNER
   • LIVE_CAPITAL_VERIFIED: ✅ TRUE
   • PRO_MODE: ✅ ENABLED
   • PLATFORM ACCOUNT: KRAKEN, $XXX.XX, ✅ CONNECTED
```

### 2. Trade Veto Logging (Shows When Blocked)
```
🚫 TRADE VETO - Signal Blocked from Execution
   Veto Reason 1: Position cap reached (7/7)
   Veto Reason 2: Insufficient balance ($15.00 < $25.00)
```

**Where it happens:** `bot/trading_strategy.py` line 3695-3703 in `run_cycle()`

---

## 📊 Last Evaluated Trade UI Panel

### API Endpoints

```bash
# Get last trade evaluation
GET http://localhost:5001/api/last-trade

# Response:
{
  "symbol": "BTC-USD",
  "signal": "BUY",
  "action": "vetoed",
  "veto_reasons": ["Insufficient balance ($15.00 < $25.00)"],
  "entry_price": 42500.00,
  "position_size": 50.00,
  "broker": "KRAKEN",
  "confidence": 0.85,
  "rsi_9": 35.2,
  "rsi_14": 38.7,
  "timestamp": "2026-02-02T23:30:00"
}

# Health check
GET http://localhost:5001/api/health

# Check simulator mode
GET http://localhost:5001/api/dry-run-status
```

### React Integration (Copy-Paste)
```javascript
const [trade, setTrade] = useState(null);

useEffect(() => {
  const fetchTrade = async () => {
    const res = await fetch('http://localhost:5001/api/last-trade');
    const data = await res.json();
    if (data.success) setTrade(data.data);
  };
  
  const interval = setInterval(fetchTrade, 5000);
  fetchTrade();
  return () => clearInterval(interval);
}, []);
```

---

## 🎭 Dry-Run Simulator Mode (App Store Review)

### Enable
```bash
DRY_RUN_MODE=true
```

### What Happens
- ✅ Evaluates signals with live market data
- ✅ Updates Last Trade API with decisions
- ✅ Shows trading logic in action
- ❌ **Does NOT place real orders**
- ❌ **Does NOT risk real money**

### Startup Banner
```
🎭 DRY-RUN SIMULATOR MODE ACTIVE
   All trades are simulated - NO REAL ORDERS PLACED
```

**Perfect for:** App Store reviewers, demos, testing

---

## 📁 Key Files

| File | Purpose | Line Reference |
|------|---------|----------------|
| `bot/trading_strategy.py` | Main strategy | - |
| └─ `_display_user_status_banner()` | Status banner | ~1309 |
| └─ `_execute_heartbeat_trade()` | Heartbeat | ~1368 |
| └─ `get_last_evaluated_trade()` | Get last trade | ~1533 |
| └─ `run_cycle()` trade veto logging | Veto reasons | 3695-3703 |
| `bot/last_trade_api.py` | REST API | - |
| `start.sh` | Startup script | Checks credentials |
| `.env.example` | Config template | - |

---

## 🐛 Troubleshooting

### Issue: Bot won't start
**Check:** `KRAKEN_PLATFORM_API_KEY` and `KRAKEN_PLATFORM_API_SECRET` are set  
**Fix:** Add both to Railway environment variables

### Issue: No trades executing
**Check logs for:** `🚫 TRADE VETO - Signal Blocked from Execution`  
**Read:** The veto reasons listed  
**Common fixes:**
- Fund account (insufficient balance)
- Wait for positions to close (position cap)
- Set `LIVE_CAPITAL_VERIFIED=true`

### Issue: Heartbeat fails
**Check:**
- Account has at least $25 balance
- "Create & Modify Orders" permission enabled on Kraken API key
- Logs show specific error

### Issue: API not responding
**Check:**
- Port 5001 is exposed
- API server started (check logs for "Last Trade API server started")
- Firewall allows port 5001

---

## 📖 Documentation

- **QUICK_START_RAILWAY.md** - 10-minute deployment
- **RAILWAY_DEPLOYMENT_KRAKEN.md** - Complete guide
- **TRADE_VETO_REFERENCE.md** - Veto function reference
- **LAST_TRADE_UI_GUIDE.md** - API + UI integration examples

---

## 🎯 Common Use Cases

### 1. Initial Deployment
```bash
KRAKEN_PLATFORM_API_KEY=xxx
KRAKEN_PLATFORM_API_SECRET=xxx
HEARTBEAT_TRADE=true
```
Deploy → Verify → Set `HEARTBEAT_TRADE=false` → Redeploy

### 2. Live Trading
```bash
KRAKEN_PLATFORM_API_KEY=xxx
KRAKEN_PLATFORM_API_SECRET=xxx
LIVE_CAPITAL_VERIFIED=true
HEARTBEAT_TRADE=false
DRY_RUN_MODE=false
```

### 3. App Store Review
```bash
DRY_RUN_MODE=true
LAST_TRADE_API_PORT=5001
```
Bot simulates, UI shows decisions, no real orders

### 4. UI Dashboard
```bash
LAST_TRADE_API_PORT=5001
DRY_RUN_MODE=false
```
Connect your React/Vue app to `http://app:5001/api/last-trade`

---

## ⚡ Quick Commands

```bash
# Test API locally
python bot/last_trade_api.py

# Check health
curl http://localhost:5001/api/health

# Get last trade
curl http://localhost:5001/api/last-trade | jq

# Monitor in real-time
watch -n 5 'curl -s http://localhost:5001/api/last-trade | jq .data'

# Test dry-run mode
export DRY_RUN_MODE=true && python bot.py
```

---

**Questions?** Check the documentation files or logs for detailed error messages.
