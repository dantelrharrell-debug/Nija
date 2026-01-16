# Quick Setup: Master Kraken Credentials

**⏱️  Time Required:** 5 minutes  
**🎯 Goal:** Enable Kraken master account trading

---

## The 5-Minute Setup

### 1️⃣ Get Kraken API Key (2 minutes)

1. Go to https://www.kraken.com/u/security/api
2. Click **"Add Key"**
3. Enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Name it: **"NIJA Master Bot"**
5. Click **"Generate Key"**
6. **Copy both API Key and Private Key** (you can't see Private Key again!)

---

### 2️⃣ Add to Deployment (2 minutes)

**Railway:**
1. Go to https://railway.app/ → Your Project → Variables
2. Add:
   - `KRAKEN_MASTER_API_KEY` = `<your-api-key>`
   - `KRAKEN_MASTER_API_SECRET` = `<your-private-key>`
3. Railway auto-restarts ✅

**Render:**
1. Go to https://dashboard.render.com/ → Your Service → Environment
2. Add:
   - `KRAKEN_MASTER_API_KEY` = `<your-api-key>`
   - `KRAKEN_MASTER_API_SECRET` = `<your-private-key>`
3. Click "Save" → "Manual Deploy"

**Local:**
```bash
cp .env.example .env
# Edit .env and set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET
./start.sh
```

---

### 3️⃣ Verify (1 minute)

Check logs for:

```
✅ Kraken MASTER connected
💰 Kraken Balance (MASTER): USD $XXX.XX
✅ Started independent trading thread for kraken (MASTER)
```

**Done!** 🎉

---

## Verification Commands

```bash
# Check if credentials are set
python3 -c "import os; print('Kraken Master:', 'SET' if os.getenv('KRAKEN_MASTER_API_KEY') else 'NOT SET')"

# Test connection (if diagnostic script exists)
python3 diagnose_master_kraken_issue.py

# Check trading status
python3 check_trading_status.py

# Verify no losing Coinbase positions
python3 audit_coinbase_positions.py
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Permission denied" | Fix API key permissions on Kraken |
| "Invalid signature" | Regenerate API key |
| "Not connecting" | Check for extra spaces in credentials |

**Full Guide:** [CONFIGURE_KRAKEN_MASTER.md](CONFIGURE_KRAKEN_MASTER.md)

---

## What This Does

**Before:**
- 1 exchange trading (Coinbase only)

**After:**
- 2 exchanges trading (Coinbase + Kraken)
- More opportunities
- Better diversification
- Independent threads (failure isolation)

---

**Questions?** Run:
```bash
python3 setup_kraken_master.py
```
