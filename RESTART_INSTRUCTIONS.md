# 🚀 NIJA BOT RESTART - IMMEDIATE ACTION STEPS

## ⚡ QUICK START (Do This Now)

### If Running on Railway (Production)

```bash
# 1. Commit and push the balance fix
cd /workspaces/Nija
git add -A
git commit -m "Fix: prefer portfolio breakdown API for balance detection"
git push origin main

# 2. Wait 30-60 seconds for Railway to redeploy
# 3. Check status
python3 check_bot_status.py
```

### If Running Locally

```bash
# 1. Make sure credentials are set
export COINBASE_API_KEY="organizations/..."
export COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\n..."

# 2. Start the bot
./restart.sh

# 3. Monitor trades
tail -f trade_journal.jsonl
```

---

## 🔧 What Was Fixed

**Problem**: Balance detection returned $0 → Bot stopped trading  
**Root Cause**: `get_accounts()` API returned empty results  
**Solution**: Switched to `get_portfolio_breakdown()` API (more reliable)

**Files Changed**:
- `bot/broker_manager.py` (lines 327-390)
- Added portfolio breakdown as primary source
- Fallback to get_accounts() if needed

---

## ✅ How to Verify Trading Restarted

### Method 1: Watch Trade Journal
```bash
tail -f trade_journal.jsonl
```
Should see new entries with recent timestamps (within last minute).

### Method 2: Run Status Check
```bash
python3 check_bot_status.py
```
Should show: **BOT IS ACTIVELY TRADING** (if trading)

### Method 3: Check Logs (Railway)
```bash
railway logs -f
```
Look for:
- `🚀 Starting ULTRA AGGRESSIVE trading loop`
- `📊 Scanning 50 markets for trading opportunities`
- `🔥 SIGNAL: XXX-USD, Signal: BUY/SELL`

---

## 📊 Current Status

| Metric | Status |
|--------|--------|
| Last Trade | Dec 20, 02:32:59 UTC (22 hours ago) |
| Bot Running | ❌ No |
| Balance Detection | ❌ Fixed (awaiting restart) |
| Credentials | ✅ Valid |

---

## 🎯 Next Steps

### For Railway Deployment
1. **Commit**: `git add -A && git commit -m "Fix: balance detection"`
2. **Push**: `git push origin main`
3. **Wait**: 30-60 seconds for redeploy
4. **Monitor**: `railway logs -f`

### For Local Testing
1. **Set Credentials**: Export COINBASE_API_KEY and COINBASE_API_SECRET
2. **Start Bot**: `./restart.sh`
3. **Verify**: `python3 check_bot_status.py`

---

## 🆘 Troubleshooting

**If bot still shows $0 balance:**
- Verify funds in Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio
- If funds in Consumer wallet: transfer to Advanced Trade (instant, no fees)
- Check: `python3 test_v2_balance.py`

**If Railway deployment stuck:**
- Force restart: `railway stop && sleep 5 && railway start`
- Check env vars: https://railway.app → Variables tab
- Verify: COINBASE_API_KEY and COINBASE_API_SECRET are set

**If local bot won't start:**
- Check Python: `python3 --version` (need 3.11+)
- Check dependencies: `pip install -r requirements.txt`
- Check credentials: `echo $COINBASE_API_KEY`

---

## 📈 Expected Results After Restart

**Within 1 minute**:
- ✅ Bot connects to Coinbase
- ✅ Fetches balance (should NOT be $0)
- ✅ Loads open positions
- ✅ Starts scanning 50 markets

**Within 5 minutes**:
- ✅ First BUY/SELL signal detected
- ✅ Trade executed
- ✅ Position tracked and monitored

**Ongoing**:
- ✅ Scans every 15 seconds
- ✅ Manages stop losses and take profits
- ✅ Logs all trades to trade_journal.jsonl

---

## 🔍 Files to Monitor

| File | Purpose |
|------|---------|
| `nija.log` | Full trading logs (tail -f) |
| `trade_journal.jsonl` | All trades with timestamps |
| `railway logs -f` | Deployment logs (if on Railway) |

---

## ✨ Summary

The bot stopped trading because balance detection failed. I've:
1. ✅ Fixed balance detection (prefer portfolio breakdown API)
2. ✅ Tested code changes locally
3. ✅ Created restart scripts
4. ✅ Added status verification tools

**To restart**: Push changes to main branch → Railway auto-redeploys → Bot trades again

**Est. time to trading**: 2-3 minutes after push
