# Quick Start: Enable Kraken Master Trading

**Time Required:** 5 minutes  
**Difficulty:** Easy  
**Impact:** Enable trading on Kraken exchange  

---

## 🎯 What This Does

Enables your master trading account to trade on Kraken exchange in addition to Coinbase.

**Before:**
- Trading on 1 exchange (Coinbase only)

**After:**
- Trading on 2+ exchanges (Coinbase + Kraken)
- More opportunities, better diversification

---

## ⚡ Quick Steps

### 1. Get Kraken API Credentials (2 minutes)

1. Go to: **https://www.kraken.com/u/security/api**
2. Click **"Generate New Key"**
3. Name it: `NIJA Master Bot`
4. Enable permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **DO NOT** enable Withdraw Funds
5. Click **"Generate Key"**
6. **Copy both keys** (API Key + Private Key)

### 2. Add to Your Deployment (2 minutes)

**Railway:**
```
1. Go to railway.app → Your Project → Variables
2. Add: KRAKEN_MASTER_API_KEY = <your-api-key>
3. Add: KRAKEN_MASTER_API_SECRET = <your-private-key>
4. Save (auto-restarts)
```

**Render:**
```
1. Go to dashboard.render.com → Your Service → Environment
2. Add: KRAKEN_MASTER_API_KEY = <your-api-key>
3. Add: KRAKEN_MASTER_API_SECRET = <your-private-key>
4. Save → Manual Deploy
```

**Local:**
```bash
# Copy .env.example to .env
cp .env.example .env

# Edit .env and set:
KRAKEN_MASTER_API_KEY=<your-api-key>
KRAKEN_MASTER_API_SECRET=<your-private-key>

# Restart bot
./start.sh
```

### 3. Verify (1 minute)

**Check logs for:**
```
✅ Kraken MASTER connected
💰 Kraken Balance (MASTER): USD $XXX.XX
✅ Started independent trading thread for kraken (MASTER)
```

**Or run:**
```bash
python3 validate_kraken_master_setup.py
```

**Expected output:**
```
✅ ALL CHECKS PASSED!
🎉 Kraken master account is properly configured and ready to trade!
```

---

## ✅ Done!

That's it! Your bot is now trading on both Coinbase and Kraken.

---

## 🔧 If Something Goes Wrong

**Error: "Permission denied"**
- Fix API key permissions on Kraken (see step 1)

**Error: "Invalid nonce"**
- Wait 1-2 minutes and restart
- Ensure you're not reusing same API key

**Still not working?**
- Read the complete guide: **KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md**
- Run diagnostic: `python3 diagnose_master_kraken_issue.py`

---

## 📚 More Information

- **Complete Guide:** [KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md](KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md)
- **Troubleshooting:** [CONFIGURE_KRAKEN_MASTER.md](CONFIGURE_KRAKEN_MASTER.md)
- **Validation Script:** `validate_kraken_master_setup.py`
- **Diagnostic Script:** `diagnose_master_kraken_issue.py`

---

**Last Updated:** January 17, 2026
