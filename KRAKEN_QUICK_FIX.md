# Kraken Trading Quick Fix Card

## 🚨 PROBLEM: No Trades Executing on Kraken

## ✅ SOLUTION: Check These Environment Variables

### Step 1: Run Diagnostic
```bash
python diagnose_kraken_trading.py
```

### Step 2: Set Required Variables

**In Railway/Render Dashboard → Environment Variables:**

```bash
# CRITICAL (must be set):
PRO_MODE=true
LIVE_TRADING=1
COPY_TRADING_MODE=MASTER_FOLLOW
KRAKEN_MASTER_API_KEY=<your-kraken-api-key>
KRAKEN_MASTER_API_SECRET=<your-kraken-api-secret>

# RECOMMENDED:
INITIAL_CAPITAL=auto
LIVE_CAPITAL_VERIFIED=true

# OPTIONAL (user accounts):
KRAKEN_USER_DAIVON_API_KEY=<daivon-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-secret>
KRAKEN_USER_TANIA_API_KEY=<tania-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-secret>
```

### Step 3: Restart Deployment

Click "Deploy" or "Restart" in your dashboard.

### Step 4: Verify in Logs

Look for these success messages:

```
✅ Kraken Master credentials detected
✅ COPY TRADE ENGINE STARTED
✅ NIJA IS READY TO TRADE!
   Connected Master Brokers: KRAKEN
```

---

## 🔍 Common Errors

| Error Message | Fix |
|--------------|-----|
| `❌ MASTER PRO_MODE=true` | Set `PRO_MODE=true` |
| `❌ LIVE_TRADING=true` | Set `LIVE_TRADING=1` |
| `❌ MASTER_BROKER=KRAKEN (connected)` | Set Kraken API keys |
| `⚠️ User requirements not met: COPY_TRADING_MODE` | Set `COPY_TRADING_MODE=MASTER_FOLLOW` |
| `⚠️ Balance < $50` | Fund account to minimum $50 |

---

## 📋 Checklist

- [ ] Set `PRO_MODE=true`
- [ ] Set `LIVE_TRADING=1`
- [ ] Set `COPY_TRADING_MODE=MASTER_FOLLOW`
- [ ] Set `KRAKEN_MASTER_API_KEY`
- [ ] Set `KRAKEN_MASTER_API_SECRET`
- [ ] Set `INITIAL_CAPITAL=auto` (recommended)
- [ ] Restart deployment
- [ ] Check logs for "✅ NIJA IS READY TO TRADE!"
- [ ] Verify Kraken connection in logs

---

## 📚 Full Documentation

- **Complete Guide**: `KRAKEN_NO_TRADES_FIX.md`
- **Diagnostic Tool**: `python diagnose_kraken_trading.py`
- **Environment Setup**: `.env.example`
- **Copy Trading Guide**: `COPY_TRADING_SETUP.md`

---

**Last Updated**: 2026-01-24
