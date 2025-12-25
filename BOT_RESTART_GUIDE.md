# 🚀 NIJA BOT RESTART GUIDE - December 21, 2025

## Status
- **Last Trades**: December 20, 02:32:59 UTC (22 hours ago)
- **Current Status**: ❌ Bot not running / Railway deployment stopped
- **Fix Applied**: Portfolio breakdown API for balance detection

## Quick Restart (3 Options)

### Option 1: Push to Railway (Recommended)
Fastest way to restart — pushes code change and triggers automatic redeploy:

```bash
cd /workspaces/Nija
git add -A
git commit -m "Fix: prefer portfolio breakdown API for balance detection"
git push origin main
```

**What happens:**
1. Code pushed to main branch
2. Railway detects change
3. Auto-redeploys bot (30-60 seconds)
4. Bot starts trading again

**Monitor progress:**
```bash
railway logs -f
# Look for: "✅ Broker connected" and "🚀 Starting ULTRA AGGRESSIVE trading loop"
```

---

### Option 2: Manual Railway Restart
If git push doesn't trigger redeploy:

```bash
# Via Railway CLI
railway deploy --service nija

# Or via web: https://railway.app → Your Project → Services → nija → Redeploy
```

---

### Option 3: Local Test (Debug Only)
Test balance detection locally:

```bash
python3 restart_bot_now.py
```

This runs 5 trading cycles to verify:
- ✅ Balance detection works
- ✅ Strategy initializes
- ✅ Trades execute

---

## What the Fix Does

**Before**: `get_accounts()` returned $0 → bot refused to trade  
**After**: `get_portfolio_breakdown()` fetches real balance → bot trades

**Changes in**: `bot/broker_manager.py`
- Lines 327-390: New portfolio breakdown logic
- Fallback to get_accounts() if needed
- Same diagnostic messages

---

## Expected Result After Restart

**Logs should show:**
```
💰 Fetching account balance via portfolio breakdown (preferred)...
   💰 Tradable USD (portfolio):  $XX.XX
   💰 Tradable USDC (portfolio): $XX.XX
   💰 Total Trading Balance: $XXX.XX
   (Source: get_portfolio_breakdown)

✅ Broker connected
🚀 Starting ULTRA AGGRESSIVE trading loop (15s cadence - 15-DAY GOAL MODE)...
📊 Scanning 50 markets for trading opportunities
🔥 SIGNAL: BTC-USD, Signal: BUY, ...
✅ Trade executed: BTC-USD BUY
```

---

## Troubleshooting

If bot still doesn't trade:

```bash
# 1. Check Railway logs for connection errors
railway logs -f | head -50

# 2. Verify balance detection works
python3 test_v2_balance.py

# 3. Check if credentials are valid
python3 test_api_permissions.py

# 4. Force restart (if stuck)
railway stop
sleep 5
railway start
```

---

## Recovery Steps (If Needed)

If balance still shows $0:

```bash
# 1. Verify funds are in Advanced Trade portfolio
# Go to: https://www.coinbase.com/advanced-portfolio

# 2. If funds are in Consumer wallet:
#    Click "Deposit" → "From Coinbase" → Transfer USD/USDC to Advanced Trade
#    (Instant transfer, no fees)

# 3. Restart bot
git push origin main

# 4. Monitor
railway logs -f
```

---

## How to Know Trading Restarted

**Real-time**: Watch logs
```bash
tail -f nija.log | grep -E "SIGNAL|Trade executed|Closed"
```

**Check trade journal**:
```bash
tail -20 trade_journal.jsonl
# Should see recent trades with current timestamp
```

**API check**:
```bash
python3 check_if_selling_now.py
# Should show: "✅ Bot IS TRADING NOW"
```

---

## Next Steps

1. **Push the fix**: `git push origin main`
2. **Wait for redeploy**: 30-60 seconds
3. **Monitor logs**: `railway logs -f`
4. **Verify trades**: `tail -f trade_journal.jsonl`

Bot should resume trading within 2 minutes of restart.
