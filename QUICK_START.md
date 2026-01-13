# NIJA Trading Bot - Quick Start Guide

## Your Bot is Already Trading! ✅

Based on your recent logs, **NIJA is actively trading on Alpaca in PAPER mode**. The Kraken errors you saw don't prevent trading - they just mean those specific accounts haven't connected yet.

## Quick Verification (30 seconds)

Run these two commands to verify everything:

```bash
# Check environment variables
python3 validate_all_env_vars.py

# Test broker connections
python3 check_trading_status.py
```

**Expected output:**
```
✅ NIJA CAN TRADE
Active Master Exchanges:
   ✅ Alpaca
```

## What the Logs Mean

### ✅ Good News (Trading Active)
```
INFO:root:✅ Alpaca MASTER connected (PAPER)
📊 Added alpaca broker (independent operation)
✅ Alpaca registered as MASTER broker
```
**Translation:** Your bot is connected and trading on Alpaca!

### ⚠️ Warnings (Doesn't Stop Trading)
```
ERROR: ❌ Kraken connection test failed (USER:daivon_frazier): 
EGeneral:Permission denied

WARNING: ⚠️ Kraken connection attempt 4/5 failed (retryable, MASTER): 
EAPI:Invalid nonce
```
**Translation:** 
- Kraken USER needs API key permission fix (manual action required)
- Kraken MASTER is retrying automatically
- **Neither affects Alpaca trading!**

## Monitor Your Bot

```bash
# Watch live trading activity
tail -f nija.log

# Or filter for important events
tail -f nija.log | grep -E "TRADE|BUY|SELL|position|scanning"
```

**What to look for:**
- Market scanning messages
- Trade signals (BUY/SELL)
- Position updates
- Balance changes

## Fix Kraken Issues (Optional)

### For User Account (daivon_frazier)

**Problem:** `EGeneral:Permission denied`

**Solution:**
1. Go to https://www.kraken.com/u/security/api
2. Find daivon's API key → Edit permissions
3. Enable these:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Save → Restart bot

**Security:** Do NOT enable "Withdraw Funds"

### For Master Account

**Problem:** `EAPI:Invalid nonce`

**Solution:**
- Usually self-heals (bot retries automatically)
- If persistent after 10 minutes:
  1. Wait 5 minutes
  2. Restart bot
  3. Check system clock is correct

## Understanding Multi-Exchange Trading

NIJA doesn't need ALL exchanges to work:

✅ **Your Situation:**
- Alpaca connected → Trading active
- Kraken not connected → Skipped for now
- **Result:** Bot trades on Alpaca only

🎯 **Add More Exchanges Later:**
- Benefits: Diversification, reduced rate limits, more opportunities
- Optional: Coinbase, Binance, OKX
- See: `MULTI_EXCHANGE_TRADING_GUIDE.md`

## Environment Variables Reference

Your `.env` file or platform variables should have:

```bash
# ALPACA (Currently Working ✅)
ALPACA_API_KEY=your-alpaca-key
ALPACA_API_SECRET=your-alpaca-secret
ALPACA_PAPER=true  # false for real money

# KRAKEN MASTER (Optional - currently has nonce issues)
KRAKEN_MASTER_API_KEY=your-kraken-key
KRAKEN_MASTER_API_SECRET=your-kraken-secret

# KRAKEN USERS (Optional - currently have permission issues)
KRAKEN_USER_DAIVON_API_KEY=daivon-key
KRAKEN_USER_DAIVON_API_SECRET=daivon-secret

KRAKEN_USER_TANIA_API_KEY=tania-key
KRAKEN_USER_TANIA_API_SECRET=tania-secret

# COINBASE (Optional - not configured yet)
COINBASE_API_KEY=organizations/.../apiKeys/...
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----..."
```

## Tools You Have

1. **validate_all_env_vars.py**
   - Checks all environment variables
   - Shows what's configured vs missing
   - Provides fix instructions

2. **check_trading_status.py**
   - Tests actual broker connections
   - Shows real-time trading readiness
   - Identifies specific errors

3. **BROKER_CONNECTION_TROUBLESHOOTING.md**
   - Complete troubleshooting guide
   - Common error solutions
   - Platform-specific instructions

4. **YOUR_TRADING_STATUS.md**
   - Detailed explanation of your situation
   - Personalized action items

## Common Questions

**Q: Is my bot trading right now?**
A: Yes! On Alpaca in PAPER mode (simulated trades with fake money).

**Q: Why does it say Kraken failed?**
A: Kraken isn't required. Alpaca is trading independently.

**Q: Should I fix Kraken?**
A: Optional. Alpaca works fine alone. Fix Kraken when you want to add it.

**Q: How do I know trades are happening?**
A: Watch logs for BUY/SELL messages and position updates.

**Q: What's the difference between PAPER and LIVE?**
A: 
- PAPER = Fake money, safe testing
- LIVE = Real money, real trades

**Q: When should I switch to LIVE?**
A: 
1. After testing in PAPER for a while
2. When comfortable with bot behavior
3. After verifying strategy works
4. **Warning:** Only use money you can afford to lose

**Q: How do I add more exchanges?**
A: 
1. Get API credentials from exchange
2. Add to environment variables
3. Restart bot
4. See: `MULTI_EXCHANGE_TRADING_GUIDE.md`

## Next Steps

### Right Now (No Action Needed)
- [x] Bot is trading on Alpaca ✅
- [x] Logs are monitoring activity ✅

### Today (Recommended)
- [ ] Run `python3 check_trading_status.py`
- [ ] Monitor logs: `tail -f nija.log`
- [ ] Read `YOUR_TRADING_STATUS.md`

### This Week (Optional)
- [ ] Fix Kraken permissions if desired
- [ ] Add Coinbase or other exchanges
- [ ] Review trading activity and results

### When Comfortable (Optional)
- [ ] Switch to live trading (change `ALPACA_PAPER=false`)
- [ ] Increase trading capital
- [ ] Enable more user accounts

## Getting Help

If something isn't working:

1. **Run diagnostics:**
   ```bash
   python3 validate_all_env_vars.py > diagnostics.txt
   python3 check_trading_status.py >> diagnostics.txt
   tail -100 nija.log >> diagnostics.txt
   ```

2. **Check documentation:**
   - `BROKER_CONNECTION_TROUBLESHOOTING.md` - Troubleshooting
   - `GETTING_STARTED.md` - Setup guide
   - `.env.example` - Environment variable template

3. **Provide context:**
   - Platform (Railway, Render, Local)
   - Error messages
   - What you were trying to do

## Summary Checklist

Quick status check:

- [x] Alpaca connected ✅
- [x] Bot trading ✅
- [ ] Kraken MASTER connected (optional)
- [ ] Kraken USERS connected (optional)
- [ ] Coinbase connected (optional)

**Bottom Line:** Your bot is working! 🎉

The Kraken errors are separate issues that don't affect Alpaca trading. You can fix them later (or not at all - Alpaca works fine standalone).

## Platform-Specific Notes

### Railway
- Variables: Dashboard → Service → Variables
- Restart: "..." menu → "Restart Deployment"
- Logs: Deployments → View Logs

### Render
- Variables: Service → Environment tab
- Restart: Auto-deploys on variable changes
- Logs: Service → Logs tab

### Local Development
- Variables: Create `.env` file in project root
- Restart: Ctrl+C → `python3 bot.py`
- Logs: Terminal output + `nija.log` file

## File Locations

```
/home/runner/work/Nija/Nija/
├── bot.py                                  # Main entry point
├── start.sh                                # Startup script
├── nija.log                                # Trading logs
├── .env.example                            # Template for variables
├── validate_all_env_vars.py               # Variable checker ⭐
├── check_trading_status.py                # Connection tester ⭐
├── YOUR_TRADING_STATUS.md                 # Your situation ⭐
├── BROKER_CONNECTION_TROUBLESHOOTING.md   # Troubleshooting ⭐
└── bot/
    ├── trading_strategy.py                # Trading logic
    └── broker_manager.py                  # Exchange connections
```

⭐ = Files created for you in this update

---

**Remember:** Your bot is already working! Everything else is optional optimization. 🚀
