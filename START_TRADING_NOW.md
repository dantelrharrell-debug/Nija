# ⚡ QUICK START: Get NIJA Trading in 60 Seconds

**Problem**: "Still no trades and the master kraken is still not connected"

**Solution**: Multiple options - choose what works for you!

---

## 🚀 Option 1: Paper Trading (FASTEST - 0 Setup)

**No API credentials needed. Start trading NOW with virtual money.**

```bash
# Auto-configure and show options
python3 enable_trading_now.py

# Or start directly
export PAPER_MODE=true
python3 bot.py
```

**What you get:**
- ✅ Trading starts immediately
- ✅ Virtual $10,000 balance
- ✅ Real market data
- ✅ No risk to real money

---

## 🎯 Option 2: Kraken Futures Demo (5 minutes)

**Free Kraken demo account with virtual funds.**

### Step 1: Get Demo Account
1. Go to: https://demo-futures.kraken.com
2. Sign up (no verification needed)
3. Get instant demo account

### Step 2: Get API Keys
1. Log in → Profile → API Settings
2. Create API key with Read + Trade permissions
3. Copy key and secret

### Step 3: Configure
```bash
# Add to Railway/Render or .env file
KRAKEN_DEMO_API_KEY=your-demo-key
KRAKEN_DEMO_API_SECRET=your-demo-secret
KRAKEN_USE_FUTURES_DEMO=true
```

### Step 4: Start
```bash
python3 quick_start_trading.py --demo-futures
```

---

## 💎 Option 3: Production Kraken (2-3 days setup)

**Real trading with real money.**

### Requirements
- Kraken account (KYC verified)
- Minimum $25-50 recommended
- API credentials

### Quick Setup
1. **Get API credentials**: https://www.kraken.com/u/security/api
2. **Enable permissions**:
   - ✅ Query Funds
   - ✅ Query/Create/Cancel Orders
   - ❌ NOT Withdraw Funds
3. **Add to environment**:
   ```bash
   KRAKEN_MASTER_API_KEY=your-key
   KRAKEN_MASTER_API_SECRET=your-secret
   ```
4. **Restart and verify**:
   ```bash
   python3 check_kraken_status.py
   ```

**See**: [SOLUTION_ENABLE_TRADING_NOW.md](SOLUTION_ENABLE_TRADING_NOW.md) for detailed steps

---

## 📊 Check Status Anytime

```bash
# Check trading status
python3 check_trading_status.py

# View paper trading account
python3 bot/view_paper_account.py

# Check Kraken connection
python3 check_kraken_status.py

# View live logs
tail -f nija.log
```

---

## 🔧 Troubleshooting

### "No trades executing"
**Solution**: Enable paper trading mode (Option 1)

### "Kraken Master not connected"
**Solutions** (pick one):
1. Use paper trading mode (no Kraken needed)
2. Use Kraken Futures demo account
3. Add production Kraken credentials

### "Missing SDK/packages"
```bash
pip install -r requirements.txt
```

---

## 📚 Documentation

- **[SOLUTION_ENABLE_TRADING_NOW.md](SOLUTION_ENABLE_TRADING_NOW.md)** - All solutions explained
- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Complete setup guide  
- **[CONFIGURE_KRAKEN_MASTER.md](CONFIGURE_KRAKEN_MASTER.md)** - Kraken setup
- **[README.md](README.md)** - Full project documentation

---

## ⚡ TL;DR - Start Trading NOW

```bash
# The absolute fastest way:
python3 enable_trading_now.py
# Then follow the instructions shown
```

**This enables paper trading automatically with NO setup required.**

---

**Status**: ✅ All dependencies installed  
**Trading**: Ready - just choose your mode above  
**Support**: See documentation files listed above
