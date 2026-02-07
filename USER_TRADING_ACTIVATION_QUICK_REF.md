# 🎯 User Trading Activation Quick Reference Card

**⏱️ Target: 10-minute activation**  
**💰 Minimum Balance: $25 USD (or $15 for small accounts)**

---

## ✅ Prerequisites Checklist

Before activating trading, ensure you have:

- [ ] Python 3.11+ installed
- [ ] Repository cloned: `git clone https://github.com/dantelrharrell-debug/Nija.git`
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Kraken account with API access enabled
- [ ] Minimum $25 USD in Kraken account (or $15 with small account config)

---

## 🔑 Step 1: Get Kraken API Credentials (3 minutes)

1. **Log in to Kraken**: https://www.kraken.com/u/security/api
2. **Create API Key**:
   - Click "Generate New Key"
   - Name: "NIJA Trading Bot - Platform"
   - **IMPORTANT**: Use "Classic API Key" (NOT OAuth)
3. **Enable Permissions**:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **DO NOT** enable "Withdraw Funds"
4. **Save Credentials**:
   - Copy API Key (starts with your key)
   - Copy Private Key (long secret string)
   - **Store securely** - you can't view them again!

---

## 🔧 Step 2: Configure Environment (2 minutes)

### Option A: Local Setup (Development)

```bash
# Copy environment template
cp .env.example .env

# Edit .env file
nano .env  # or use your preferred editor
```

**Add your credentials:**
```bash
# REQUIRED - Kraken Platform Account
KRAKEN_PLATFORM_API_KEY=your-api-key-here
KRAKEN_PLATFORM_API_SECRET=your-api-secret-here

# REQUIRED - Enable live trading
LIVE_CAPITAL_VERIFIED=true

# OPTIONAL - For small accounts ($15-$25)
MINIMUM_TRADING_BALANCE=15.0
MIN_CASH_TO_BUY=5.0
```

### Option B: Railway Deployment (Production)

1. Go to Railway dashboard → Your project
2. Navigate to **Variables** tab
3. Add environment variables:
   - `KRAKEN_PLATFORM_API_KEY` = your-api-key
   - `KRAKEN_PLATFORM_API_SECRET` = your-api-secret
   - `LIVE_CAPITAL_VERIFIED` = true
4. Click **Deploy**

---

## 🚀 Step 3: Activate Trading (1 minute)

### Start the Bot

**Local:**
```bash
python3 bot.py
```

**Railway:**
- Automatically starts after deployment
- View logs in Railway dashboard

### Expected Startup Output

```
✅ KRAKEN PLATFORM: CONNECTED
💰 Platform Account Balance: $XXX.XX USD
🔷 PLATFORM ACCOUNT: TRADING ACTIVE
🧠 TRUST LAYER - USER STATUS BANNER
   • LIVE_CAPITAL_VERIFIED: ✅ TRUE
   • PRO_MODE: ✅ ENABLED
   • PLATFORM ACCOUNT: KRAKEN, $XXX.XX, ✅ CONNECTED
```

✅ **Success!** Trading is now active!

---

## 🔍 Step 4: Verify Activation (30 seconds)

### Quick Verification Commands

```bash
# Check bot status
curl http://localhost:5001/api/health

# View last trade evaluation (if API enabled)
curl http://localhost:5001/api/last-trade

# Check live status in logs
tail -f logs/nija.log  # if logging to file
```

### Manual Verification

1. **Check Kraken Dashboard**:
   - Go to: https://www.kraken.com/u/history
   - Wait 2-5 minutes
   - Look for new orders when signals trigger

2. **Monitor Logs**:
   - Look for: `🎯 BUY signal detected for BTC-USD`
   - Or: `🚫 TRADE VETO - Signal Blocked from Execution`

---

## 🎭 Optional: Test Mode (Heartbeat Trade)

### Quick Verification Trade

Test that everything works with a single small trade:

```bash
# In .env or Railway Variables
HEARTBEAT_TRADE=true
```

**What it does:**
1. Executes ONE small trade (~$5-10)
2. Verifies API credentials work
3. Immediately sells position
4. Shuts down bot

**After verification:**
1. Set `HEARTBEAT_TRADE=false`
2. Restart bot for normal trading

---

## 🧪 Optional: Dry-Run Mode (No Real Money)

Test strategy logic without real trades:

```bash
# In .env or Railway Variables
DRY_RUN_MODE=true
LIVE_CAPITAL_VERIFIED=false
```

**What it does:**
- ✅ Evaluates signals with live market data
- ✅ Shows trading decisions in logs
- ✅ Updates last trade API (if enabled)
- ❌ **Does NOT place real orders**
- ❌ **Does NOT risk real money**

**For live trading, set both to:**
```bash
DRY_RUN_MODE=false
LIVE_CAPITAL_VERIFIED=true
```

---

## 🛡️ Safety Features (Always Active)

NIJA includes automatic safety controls:

| Feature | Description | Can Disable? |
|---------|-------------|--------------|
| **LIVE_CAPITAL_VERIFIED** | Master kill-switch for live trading | Required |
| **Position Limits** | Max 7 concurrent positions | No |
| **Minimum Balance** | Won't trade below $25 (or configured) | Configurable |
| **Stop Losses** | Automatic on every position | No |
| **Trade Vetos** | Blocks bad setups | No |
| **Risk Limits** | Max 2-15% per trade (tier-based) | No |

---

## 🔧 Common Configuration Options

### Environment Variables Quick Reference

```bash
# === REQUIRED ===
KRAKEN_PLATFORM_API_KEY=           # Your Kraken API key
KRAKEN_PLATFORM_API_SECRET=        # Your Kraken secret
LIVE_CAPITAL_VERIFIED=true         # Enable live trading

# === SAFETY & MODE ===
HEARTBEAT_TRADE=false              # true = 1 test trade then exit
DRY_RUN_MODE=false                 # true = simulate (no real orders)
PRO_MODE=true                      # Position rotation trading

# === POSITION MANAGEMENT ===
MAX_CONCURRENT_POSITIONS=7         # Max open positions
MIN_CASH_TO_BUY=5.50              # Min USD to place order
MINIMUM_TRADING_BALANCE=25.0       # Min balance to trade

# === SMALL ACCOUNT MODE ($15-$25) ===
MINIMUM_TRADING_BALANCE=15.0       # Lower minimum
MIN_CASH_TO_BUY=5.0               # Lower order min

# === RISK MANAGEMENT ===
KRAKEN_MIN_RSI=35                  # Min RSI for entry (30-70 range)
KRAKEN_MAX_RSI=65                  # Max RSI for entry (30-70 range)
KRAKEN_MIN_CONFIDENCE=0.65         # Min confidence (0.0-1.0)
KRAKEN_MIN_ATR_PCT=0.6            # Min volatility % (0.5-1.0)

# === OPTIONAL FEATURES ===
LAST_TRADE_API_PORT=5001          # Enable last trade API
ENABLE_SYMBOL_WHITELIST=false      # true = BTC/ETH/SOL only
PLATFORM_ACCOUNT_TIER=BALLER       # Force tier (BALLER/INVESTOR/etc)
```

---

## 🐛 Troubleshooting

### Issue: Bot won't start

**Symptom:** Error on startup or immediate exit

**Solutions:**
1. ✅ Check `KRAKEN_PLATFORM_API_KEY` is set correctly
2. ✅ Check `KRAKEN_PLATFORM_API_SECRET` is set correctly
3. ✅ Verify no extra spaces in credentials
4. ✅ Ensure `.env` file exists (local) or variables set (Railway)
5. ✅ Run: `python3 -c "from dotenv import load_dotenv; load_dotenv(); import os; print('Key:', bool(os.getenv('KRAKEN_PLATFORM_API_KEY')))"`

---

### Issue: No trades executing

**Symptom:** Bot runs but never places orders

**Check logs for:**
```
🚫 TRADE VETO - Signal Blocked from Execution
   Veto Reason: [reason listed here]
```

**Common reasons:**
- ❌ Insufficient balance → **Fund account with at least $25**
- ❌ Position cap reached (7/7) → **Wait for positions to close**
- ❌ `LIVE_CAPITAL_VERIFIED=false` → **Set to `true`**
- ❌ `DRY_RUN_MODE=true` → **Set to `false` for real trading**
- ❌ No valid signals → **Wait for market conditions**

---

### Issue: "Permission denied" errors

**Symptom:** API errors about permissions

**Solution:**
1. Go to: https://www.kraken.com/u/security/api
2. Edit your API key
3. Ensure ALL required permissions are enabled:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Save changes
5. Restart bot

---

### Issue: Heartbeat trade fails

**Symptom:** Error during heartbeat verification

**Solutions:**
1. ✅ Ensure account has at least $25 balance
2. ✅ Verify "Create & Modify Orders" permission is enabled
3. ✅ Check Kraken isn't in maintenance mode
4. ✅ Review error message in logs for specific issue

---

### Issue: Environment variables not loading

**Local Development:**
```bash
# Check .env file exists
ls -la .env

# Verify python-dotenv installed
pip install python-dotenv

# Test loading
python3 -c "from dotenv import load_dotenv; load_dotenv(); import os; print('Loaded:', list(os.environ.keys())[:5])"
```

**Production (Railway):**
1. Go to Variables tab
2. Verify variables are listed
3. Check for typos in variable names
4. Redeploy after adding variables

---

## 📊 Monitoring Your Trading

### Watch Real-Time Activity

**Logs (Local):**
```bash
# Follow logs in real-time
tail -f logs/nija.log

# Or if logging to console
python3 bot.py  # watch output
```

**Logs (Railway):**
1. Go to Railway dashboard
2. Click on your service
3. Click **Logs** tab
4. Watch real-time output

### Key Log Messages

| Message | Meaning |
|---------|---------|
| `🎯 BUY signal detected` | Found potential entry |
| `✅ BUY order placed` | Entered position |
| `🎯 SELL signal detected` | Time to exit |
| `✅ SELL order executed` | Position closed |
| `🚫 TRADE VETO` | Signal blocked (see reason) |
| `💰 Platform Account Balance: $XXX` | Current capital |

### Check Positions in Kraken

1. Go to: https://www.kraken.com/u/trading
2. Click **Positions** tab
3. See all open positions
4. Review open orders
5. Check trade history

---

## 🎓 Trading Strategy Overview

NIJA uses a dual RSI strategy with intelligent position management:

### Signal Generation
- **RSI_9**: Short-term momentum (9-period)
- **RSI_14**: Medium-term momentum (14-period)
- **Entry**: Both RSI indicators show oversold/overbought
- **Confidence Score**: 0.60-1.0 (higher = better setup)

### Position Management
- **Stop Loss**: Automatic on every trade
- **Trailing Stops**: Locks in profits
- **Position Sizing**: 2-10% of capital (tier-based)
- **Max Positions**: 7 concurrent trades
- **Pro Mode**: Can rotate positions for better opportunities

### Risk Controls
- Minimum confidence threshold (0.60-0.65)
- ATR volatility filter (0.5-0.6%)
- RSI range filter (30-70, configurable)
- Maximum position limits
- Minimum balance requirements

---

## 📚 Additional Resources

| Document | Purpose | Use When |
|----------|---------|----------|
| **GETTING_STARTED.md** | Complete setup guide | First-time setup |
| **API_CREDENTIALS_GUIDE.md** | Credential management | API issues |
| **KRAKEN_TRADING_GUIDE.md** | Kraken-specific help | Using Kraken |
| **QUICK_REFERENCE.md** | General features | Feature overview |
| **APEX_V71_DOCUMENTATION.md** | Strategy details | Understanding signals |
| **TRADE_VETO_REFERENCE.md** | Veto system details | Trade not executing |
| **.env.example** | All config options | Configuration help |

---

## 🆘 Emergency Controls

### Stop All Trading Immediately

**Option 1: Kill-Switch (Fastest)**
```bash
python emergency_kill_switch.py activate emergency
```

**Option 2: Environment Variable**
```bash
# Set in .env or Railway
LIVE_CAPITAL_VERIFIED=false
# Restart bot
```

**Option 3: File System**
```bash
touch EMERGENCY_STOP
```

### Close All Positions Manually

If you need to close positions manually:

1. Go to: https://www.kraken.com/u/trading
2. Click on each open position
3. Click **Close Position**
4. Confirm closure

Or use Kraken mobile app for quick access.

---

## ✅ Activation Success Checklist

After activation, you should see:

- [x] Bot starts without errors
- [x] Logs show "✅ KRAKEN PLATFORM: CONNECTED"
- [x] Status banner shows "LIVE_CAPITAL_VERIFIED: ✅ TRUE"
- [x] Account balance displayed correctly
- [x] Monitoring logs for signals
- [x] Can see positions in Kraken dashboard

**If all checked: You're live trading! 🎉**

---

## 🎯 Quick Command Reference

```bash
# === SETUP ===
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija
pip install -r requirements.txt
cp .env.example .env
nano .env  # Add credentials

# === START TRADING ===
python3 bot.py

# === MONITORING ===
tail -f logs/nija.log                              # Watch logs
curl http://localhost:5001/api/last-trade          # Last trade API
curl http://localhost:5001/api/health              # Health check

# === TESTING ===
export HEARTBEAT_TRADE=true && python3 bot.py      # Test trade
export DRY_RUN_MODE=true && python3 bot.py         # Simulate only

# === EMERGENCY ===
python emergency_kill_switch.py activate emergency  # Stop trading
```

---

## 💬 Support & Next Steps

### Need Help?

1. **Check logs** for specific error messages
2. **Review this guide** and troubleshooting section
3. **Check documentation** in Additional Resources
4. **Open issue** on GitHub (remove credentials from logs!)

### Next Steps After Activation

1. ✅ **Monitor first 24 hours** closely
2. ✅ **Review trades** in Kraken dashboard
3. ✅ **Adjust configuration** if needed (risk levels, RSI ranges)
4. ✅ **Set up alerts** (email/SMS for important events)
5. ✅ **Read strategy docs** (APEX_V71_DOCUMENTATION.md)
6. ✅ **Consider TradingView webhooks** (TRADINGVIEW_SETUP.md)

---

**Version:** 1.0  
**Last Updated:** February 7, 2026  
**Status:** Ready for Production Use

---

**⚠️ Trading Disclaimer**: Cryptocurrency trading carries substantial risk. Only trade with capital you can afford to lose. Past performance does not guarantee future results. NIJA is provided as-is without warranty.
