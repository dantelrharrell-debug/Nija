# Kraken MICRO_CAP Validation - Quick Reference

## 🚀 Quick Start (3 Steps)

### 1. Setup Environment
```bash
# Copy micro capital config
cp .env.micro_capital .env

# Add your Kraken API credentials
nano .env
# Set: KRAKEN_PLATFORM_API_KEY=your_key
# Set: KRAKEN_PLATFORM_API_SECRET=your_secret
```

### 2. Run Validation
```bash
# DRY-RUN (always first!)
python scripts/kraken_micro_cap_validation.py --dry-run

# Expected: ✅ ALL VALIDATIONS PASSED
```

### 3. Enable Live Trading
```bash
# In .env, set:
LIVE_CAPITAL_VERIFIED=true

# Start bot
./start.sh
```

---

## 📋 Validation Checklist

| Check | Requirement | Pass/Fail |
|-------|-------------|-----------|
| 🔑 API Key | KRAKEN_PLATFORM_API_KEY set | ☐ |
| 🔐 API Secret | KRAKEN_PLATFORM_API_SECRET set | ☐ |
| 💰 Balance | $25-$50 USD in account | ☐ |
| 🎯 Mode | MICRO_CAP auto-selected | ☐ |
| 📊 Pairs | BTC/ETH/SOL available | ☐ |
| ⚖️ Orders | $20 position meets $10 min | ☐ |
| 🕐 Rate | 30s entry, 2 max/min | ☐ |
| 📈 Position | 1 max, $20 size | ☐ |
| ⚠️ Risk | 2:1 reward/risk ratio | ☐ |
| ✅ Test | Dry-run order passed | ☐ |

---

## 🎯 MICRO_CAP Configuration

```
Balance Range:    $20-$100
Max Positions:    1
Position Size:    $20
Profit Target:    2% ($0.40)
Stop Loss:        1% ($0.20)
Risk/Reward:      2:1
Entry Interval:   30 seconds
Max Entries/Min:  2
Quality Filter:   75% minimum
```

---

## 🛡️ Safety Commands

```bash
# Check validation status
python scripts/kraken_micro_cap_validation.py --dry-run

# Emergency cleanup (cancel all orders)
python scripts/emergency_cleanup.py --broker kraken --dry-run

# Check trading status
python scripts/check_trading_status.py

# View bot logs
tail -f logs/nija.log

# Stop bot immediately
Ctrl+C
```

---

## 📊 Expected Performance

| Metric | Value |
|--------|-------|
| Win | +$0.40 (2%) |
| Loss | -$0.20 (1%) |
| Daily (8 trades, 50% win) | +$0.80 |
| Monthly (estimate) | +$24 (48% ROI) |
| Conservative (40% win) | +$4.80/month (9.6% ROI) |

---

## ⚠️ Common Issues

### Missing Credentials
```bash
# Get from: https://www.kraken.com/u/security/api
# Required permissions: Query Funds, Query/Create/Cancel Orders, Query Trades
```

### Balance Too Low
```bash
# Deposit to reach $25-$50 range
# Or adjust: --min-balance 20 (not recommended)
```

### SDK Not Installed
```bash
pip install krakenex pykrakenapi
```

### Connection Failed
```bash
# Check internet connection
# Verify Kraken status: https://status.kraken.com
# Retry in a few minutes
```

---

## 📞 Support Resources

| Resource | Location |
|----------|----------|
| Full Guide | `KRAKEN_MICRO_CAP_VALIDATION_GUIDE.md` |
| MICRO_CAP Details | `IMPLEMENTATION_SUMMARY_MICRO_CAP.md` |
| Algorithm | `MICRO_CAP_ENGINE_PSEUDOCODE.md` |
| Kraken UI | `KRAKEN_TRADING_GUIDE.md` |
| Config Example | `.env.micro_capital` |

---

## ✅ Go-Live Checklist

Before enabling LIVE_CAPITAL_VERIFIED=true:

- [ ] Validation passes with --dry-run
- [ ] Balance confirmed $25-$50
- [ ] MICRO_CAPITAL_MODE=true in .env
- [ ] API credentials valid
- [ ] Emergency cleanup tested
- [ ] Know how to stop bot
- [ ] Can view trades in Kraken UI
- [ ] Monitoring plan ready

---

## 🚨 Emergency Procedures

### Stop Trading Immediately
```bash
# Stop bot
Ctrl+C

# Or kill process
pkill -f bot.py
```

### Cancel All Orders
```bash
# Dry-run first
python scripts/emergency_cleanup.py --broker kraken --dry-run

# Live execution
python scripts/emergency_cleanup.py --broker kraken
```

### Disable Live Trading
```bash
# In .env:
LIVE_CAPITAL_VERIFIED=false

# Restart bot (will run in paper mode)
./start.sh
```

---

## 💡 Pro Tips

1. **Always dry-run first** - Test before live
2. **Start small** - Begin with $25-30
3. **Monitor closely** - Watch first 24 hours
4. **Be patient** - MICRO_CAP trades slowly (by design)
5. **Keep buffer** - Maintain 15%+ cash reserve
6. **Quality over quantity** - 2 trades/min max
7. **Trust the system** - 30s entry interval is intentional
8. **Emergency ready** - Know cleanup commands

---

## 📈 Trading Philosophy

**MICRO_CAP Mode:**
- ✅ Preserves capital (1% stop loss)
- ✅ High quality signals only (75%+)
- ✅ Single focused position
- ✅ Patient entry (30s intervals)
- ✅ 2:1 reward/risk ratio

**NOT for:**
- ❌ Scalping
- ❌ High-frequency trading
- ❌ Multiple positions
- ❌ Averaging down
- ❌ Chasing momentum

---

## 🎓 Learn More

```bash
# Read full documentation
cat KRAKEN_MICRO_CAP_VALIDATION_GUIDE.md

# Review MICRO_CAP implementation
cat IMPLEMENTATION_SUMMARY_MICRO_CAP.md

# Study algorithm
cat MICRO_CAP_ENGINE_PSEUDOCODE.md

# Check example config
cat .env.micro_capital
```

---

**Remember: MICRO_CAP success = Patience + Quality + Discipline**

*Good luck! 🚀*
