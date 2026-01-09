# 🚀 NIJA Trading Status - Start Here

**Quick Question:** Is NIJA actively trading for me and other users?

**Quick Answer:** Choose the fastest method below to check.

---

## ⚡ Check Right Now (Pick One)

### Option 1: Web Browser (Easiest) 🌐

Open in your browser:
```
http://localhost:5001/status
```

Or on your deployment:
```
https://your-app.railway.app/status
```

**Shows:**
- 🟢 **ACTIVE** = Trading with open positions
- 🟡 **READY** = Running, waiting for signals (normal)
- 🔴 **STOPPED** = Not running (needs attention)

Page auto-refreshes every 10 seconds.

---

### Option 2: Shell Command (Fast) 💻

```bash
./check_active_trading.sh
```

Automatically tries:
1. HTTP endpoint (if available)
2. Comprehensive Python script
3. Fallback status checks

---

### Option 3: Python Script (Detailed) 🐍

```bash
python check_trading_status.py
```

Shows complete status including:
- Bot process activity
- Open positions per broker
- Trading balance
- Recent trades (24h)
- User status

---

### Option 4: API Call (Automation) 🔧

```bash
curl http://localhost:5001/api/trading_status
```

Returns JSON with full status data.

---

## 📚 Documentation

### Quick Reference
**[README_TRADING_STATUS.md](README_TRADING_STATUS.md)** - 1-page quick reference

### Complete Guide
**[ACTIVE_TRADING_STATUS.md](ACTIVE_TRADING_STATUS.md)** - Full documentation with:
- Status level explanations (ACTIVE/READY/STOPPED)
- Integration examples
- Troubleshooting guide
- API reference
- Best practices

### Other Status Guides
- **[IS_NIJA_TRADING_NOW.md](IS_NIJA_TRADING_NOW.md)** - Original detailed guide
- **[ACTIVE_TRADING_STATUS_PER_BROKER.md](ACTIVE_TRADING_STATUS_PER_BROKER.md)** - Per-broker breakdown
- **[IS_USER1_TRADING.md](IS_USER1_TRADING.md)** - User-specific status

---

## 🔍 All Status Check Methods

| Method | Type | When to Use |
|--------|------|-------------|
| `/status` webpage | Web | Quick visual check, monitor in browser |
| `/api/trading_status` | API | Automation, integrations, monitoring tools |
| `./check_active_trading.sh` | Shell | Quick command line check |
| `python check_trading_status.py` | Python | Comprehensive local diagnostic |
| `python check_if_trading_now.py` | Python | Alternative local check |
| `python check_active_trading_per_broker.py` | Python | Detailed per-broker analysis |
| `python check_first_user_trading_status.py` | Python | User-specific trading status |

---

## 🎯 What Status Levels Mean

### 🟢 ACTIVE - Actively Trading
**Indicators:**
- ✅ Bot is running (log file updated < 5 min ago)
- ✅ Has open positions (≥ 1)
- ✅ Recent trades detected (last 24h)

**What to expect:**
- Positions being managed automatically
- Trades executed based on strategy
- Stop losses and profit targets active

**Action needed:** None - working normally

---

### 🟡 READY - Running but Not Trading
**Indicators:**
- ✅ Bot is running (log file active)
- ❌ No open positions currently
- ℹ️ May have recent trades (all closed)

**Why this happens:**
- Waiting for entry signals
- Strategy requires specific RSI conditions
- All positions recently closed
- Normal operation

**Action needed:** None - be patient, bot scans every 2.5 min

---

### 🔴 STOPPED - Not Running
**Indicators:**
- ❌ Bot not running (log file stale)
- ❌ No open positions
- ❌ No recent trading activity

**Common causes:**
1. Deployment stopped/crashed
2. Insufficient balance (< $25)
3. API credentials invalid
4. Manual shutdown
5. Startup error

**Actions to take:**
1. Check deployment status (Railway/Render)
2. View logs for errors
3. Verify broker balance ≥ $25
4. Check API credentials in .env
5. Restart the bot

---

## 🚀 Starting the Dashboard Server

The dashboard server provides HTTP endpoints (/status, /api/trading_status).

**Manual start:**
```bash
cd bot
python dashboard_server.py
```

**Auto-start with bot:**
Add to `start.sh`:
```bash
python bot/dashboard_server.py &
python bot.py
```

**Access:**
- Dashboard: http://localhost:5001/
- Status: http://localhost:5001/status
- API: http://localhost:5001/api/trading_status
- Health: http://localhost:5001/health

---

## ❓ Common Questions

**Q: How often should I check?**  
A: The web page auto-refreshes every 10 seconds. Manual checks every 30-60 minutes are sufficient.

**Q: Status shows READY but I want it to trade**  
A: This is normal. The bot only enters when specific conditions are met (RSI_9 < 35 or RSI_14 < 40). Be patient.

**Q: Can I check from my phone?**  
A: Yes! Visit `https://your-app.railway.app/status` on any device.

**Q: Endpoints don't respond**  
A: Dashboard server needs to be running. Use Python script instead: `python check_trading_status.py`

**Q: How do I know if it's working for my user account?**  
A: The `/api/trading_status` endpoint includes a `users` array with per-user status (if multi-user system is active).

---

## 🔗 Quick Links

- **[Main README](README.md)** - Project overview
- **[ACTIVE_TRADING_STATUS.md](ACTIVE_TRADING_STATUS.md)** - Complete status guide
- **[TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md)** - Common issues
- **[APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)** - Trading strategy

---

## 📞 Need Help?

1. Read [ACTIVE_TRADING_STATUS.md](ACTIVE_TRADING_STATUS.md) troubleshooting section
2. Run `python check_trading_status.py` for diagnostics
3. Check deployment logs (Railway/Render)
4. Verify API credentials and balance
5. Review [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md)

---

**TL;DR:** Visit http://localhost:5001/status or run `./check_active_trading.sh`

---

*Last Updated: January 9, 2026*
