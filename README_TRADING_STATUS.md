# Is NIJA Trading for Me? - Quick Reference

**Last Updated:** January 9, 2026

---

## ⚡ Quick Answer

### Check Right Now (Choose One):

#### 1. **Web Browser** (Easiest)
```
http://localhost:5001/status
```
Or: `https://your-app.railway.app/status`

**Shows:**
- 🟢 ACTIVE = Trading now with open positions
- 🟡 READY = Running, waiting for signals
- 🔴 STOPPED = Not running

---

#### 2. **Shell Script**
```bash
./check_active_trading.sh
```

---

#### 3. **Python Script**
```bash
python check_trading_status.py
```

**Shows:**
- ✅ Bot running status
- 📊 Open positions
- 💰 Trading balance
- 📈 Recent trades (24h)
- 👥 User status

---

#### 4. **API Call**
```bash
curl http://localhost:5001/api/trading_status
```

Returns JSON with complete status.

---

## 📖 Complete Documentation

**[ACTIVE_TRADING_STATUS.md](ACTIVE_TRADING_STATUS.md)** - Full guide with:
- Detailed status explanations
- Integration examples
- Troubleshooting
- API reference

---

## What Each Status Means

### 🟢 ACTIVE - Actively Trading
✅ Bot is running  
✅ Has open positions  
✅ Recent trading activity  

**Action:** None needed - bot is working normally

---

### 🟡 READY - Running but Not Trading
✅ Bot is running  
❌ No open positions  
ℹ️ Waiting for entry signals  

**Action:** None needed - this is normal!  
The strategy only enters high-quality trades. Market conditions may not meet entry criteria yet.

---

### 🔴 STOPPED - Not Running
❌ Bot is not running  
❌ No trading activity  

**Check:**
1. Deployment status (Railway/Render)
2. View logs for errors
3. Verify balance (need $25+)
4. Check API credentials

---

## Starting the Dashboard Server

The dashboard server provides HTTP endpoints and web interface.

**Start manually:**
```bash
cd bot
python dashboard_server.py
```

**Access:**
- Dashboard: http://localhost:5001/
- Status Page: http://localhost:5001/status
- API: http://localhost:5001/api/trading_status
- Health: http://localhost:5001/health

---

## Common Questions

**Q: Status shows READY but I want it to trade**  
**A:** This is normal. The bot scans markets every 2.5 minutes and only enters when specific RSI conditions are met (RSI_9 < 35 or RSI_14 < 40). Be patient.

**Q: How often should I check?**  
**A:** The web status page auto-refreshes every 10 seconds. For manual checks, every 30-60 minutes is reasonable.

**Q: Can I check status from my phone?**  
**A:** Yes! If the dashboard is deployed, visit `https://your-app.railway.app/status` on any device.

**Q: What if endpoints don't respond?**  
**A:** The dashboard server needs to be running. If not, use the Python script: `python check_trading_status.py`

---

## All Status Check Tools

| Tool | Type | Best For |
|------|------|----------|
| `/status` webpage | Web | Quick visual check |
| `/api/trading_status` | API | Automation/monitoring |
| `check_trading_status.py` | Script | Comprehensive local check |
| `check_active_trading.sh` | Shell | Quick command-line check |
| `check_if_trading_now.py` | Script | Alternative checker |
| `check_active_trading_per_broker.py` | Script | Per-broker breakdown |
| `check_first_user_trading_status.py` | Script | User-specific check |

---

## Related Documentation

- **[ACTIVE_TRADING_STATUS.md](ACTIVE_TRADING_STATUS.md)** - Complete guide (recommended)
- **[IS_NIJA_TRADING_NOW.md](IS_NIJA_TRADING_NOW.md)** - Original status guide
- **[README.md](README.md)** - Main project documentation
- **[TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md)** - Common issues

---

## Support

If you need help:
1. Check [ACTIVE_TRADING_STATUS.md](ACTIVE_TRADING_STATUS.md) for detailed troubleshooting
2. Run `python check_trading_status.py` for diagnostic info
3. Check deployment logs (Railway/Render)
4. Verify Coinbase balance and API credentials

---

*Quick reference created: January 9, 2026*
