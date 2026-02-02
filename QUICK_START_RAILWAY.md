# 🎯 Quick Start: Kraken Platform Deployment

## Immediate Action Items (10 minutes)

### 1️⃣ Add Environment Variables to Railway

Go to Railway → Your Service → Variables tab and add:

```bash
KRAKEN_PLATFORM_API_KEY=<your-api-key-here>
KRAKEN_PLATFORM_API_SECRET=<your-api-secret-here>
```

**Get credentials from:** https://www.kraken.com/u/security/api  
**Use:** Classic API Key (NOT OAuth)

### 2️⃣ Redeploy Railway

Click **"Redeploy"** in Railway dashboard after adding the variables.

---

## 🔍 Verification (Heartbeat Test)

To verify your API credentials work:

1. **Add to Railway variables:**
   ```bash
   HEARTBEAT_TRADE=true
   ```

2. **Deploy** and watch logs

3. **Look for:**
   ```
   💓 HEARTBEAT TRADE VERIFICATION: ✅ SUCCESS
   ```

4. **After success, change back:**
   ```bash
   HEARTBEAT_TRADE=false
   ```

5. **Redeploy** to resume normal trading

---

## 🧠 Trust Layer - What You Get

### User Status Banner
On every startup, you see:
```
===============================================================
🧠 TRUST LAYER - USER STATUS BANNER
===============================================================
📋 SAFETY SETTINGS:
   • LIVE_CAPITAL_VERIFIED: ✅ TRUE
   • PRO_MODE: ✅ ENABLED

📊 PLATFORM ACCOUNT:
   • Broker: KRAKEN
   • Balance: $XXX.XX
   • Status: ✅ CONNECTED
===============================================================
```

### Trade Veto Logging
When trades are blocked:
```
======================================================================
🚫 TRADE VETO - Signal Blocked from Execution
======================================================================
   Veto Reason 1: Insufficient balance ($15.00 < $25.00)
======================================================================
```

**This tells you exactly why trades aren't executing!**

---

## 📍 Where Trade Vetoes Happen

**File:** `bot/trading_strategy.py`  
**Function:** `run_cycle()` method  
**Lines:** 3485-3703

See **TRADE_VETO_REFERENCE.md** for detailed breakdown.

---

## ⚙️ Key Environment Variables

```bash
# Required for trading
KRAKEN_PLATFORM_API_KEY=<your-key>
KRAKEN_PLATFORM_API_SECRET=<your-secret>
LIVE_CAPITAL_VERIFIED=true

# Optional but recommended
PRO_MODE=true
PLATFORM_ACCOUNT_TIER=BALLER
HEARTBEAT_TRADE=false

# Trading limits
MIN_CASH_TO_BUY=5.50
MINIMUM_TRADING_BALANCE=25.0
MAX_CONCURRENT_POSITIONS=7
```

---

## ✅ Success Checklist

After Railway deployment, verify in logs:

- [ ] `✅ Kraken PLATFORM connected`
- [ ] Platform balance shows correctly
- [ ] `🚀 TRADING ACTIVE: 1 account(s) ready`
- [ ] No `❌ TRADE VETO` messages (unless expected)

---

## 🚨 Common Issues

### Issue: No trades executing
**Check logs for:** `🚫 TRADE VETO - Signal Blocked from Execution`  
**Solution:** Read the veto reasons and address them

### Issue: Connection failed
**Check:** API key/secret are correct  
**Check:** All required permissions enabled in Kraken  
**Try:** Redeploy after a few minutes

### Issue: Heartbeat fails
**Check:** Account has at least $25 balance  
**Check:** "Create & Modify Orders" permission enabled  
**Try:** Run heartbeat again after fixing

---

## 📚 Full Documentation

- **Deployment Guide:** `RAILWAY_DEPLOYMENT_KRAKEN.md`
- **Veto Reference:** `TRADE_VETO_REFERENCE.md`
- **Configuration:** `.env.example`

---

## 🎉 You're Done!

After successful deployment:
1. Monitor first few trades
2. Check veto logs if no trades execute
3. Verify positions close properly
4. Scale up gradually

**Remember:** Start small, monitor closely, verify execution works!
