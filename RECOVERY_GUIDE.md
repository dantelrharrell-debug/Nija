# Recovery Guide - Return to Success State

**Last Updated**: January 25, 2026
**Success Checkpoint**: Kraken Platform + Multi-User Independent Trading with Full Profit-Taking

## 🎯 Purpose

This guide provides **step-by-step instructions** to restore NIJA to the verified working state where:
- ✅ Platform account trading successfully on Kraken
- ✅ 2 user accounts trading independently
- ✅ 100% success rate on profit-taking
- ✅ All risk management and position sizing working correctly

---

## 📋 Success State Reference

### Git Reference Points

**Branch**: `copilot/update-readme-for-success-lock`
**Tag**: `success-kraken-copy-trading-2026-01-25` (local)
**Commit**: `cac2d97` (Archive historical documentation and create cleanup guide)

### Documentation
- **Complete Details**: [SUCCESS_STATE_2026_01_25.md](SUCCESS_STATE_2026_01_25.md)
- **Cleanup Guide**: [REPOSITORY_CLEANUP_GUIDE.md](REPOSITORY_CLEANUP_GUIDE.md)

---

## 🔄 Recovery Methods

### Method 1: Git Reset (Recommended)

**When to Use**: You want to return to the exact code state

```bash
# Navigate to repository
cd /home/runner/work/Nija/Nija

# Fetch latest from remote
git fetch origin

# Reset to success checkpoint branch
git checkout copilot/update-readme-for-success-lock
git pull origin copilot/update-readme-for-success-lock

# Verify you're at the right commit
git log --oneline -5
# Should show: cac2d97 Archive historical documentation and create cleanup guide

# Check for success state documentation
ls -la SUCCESS_STATE_2026_01_25.md
```

### Method 2: Tag-Based Recovery (Local Only)

**When to Use**: Tag exists locally and you want to restore from it

```bash
# Check if tag exists
git tag -l | grep success-kraken

# Checkout the tag
git checkout success-kraken-copy-trading-2026-01-25

# Create a new branch from tag
git checkout -b recovery-from-success
```

### Method 3: Environment-Only Recovery

**When to Use**: Code is correct but configuration needs fixing

**This is the FASTEST method if your code is already up to date!**

Just verify environment variables are set correctly:

```bash
# Master Kraken credentials
KRAKEN_PLATFORM_API_KEY=<your-master-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-master-api-secret>

# User #1 (Daivon Frazier) credentials
KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>

# User #2 (Tania Gilbert) credentials
KRAKEN_USER_TANIA_API_KEY=<tania-api-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>

# Copy trading mode
COPY_TRADING_MODE=MASTER_FOLLOW

# Optional but recommended
PORT=5000
WEB_CONCURRENCY=1
```

Then restart the bot:
```bash
./start.sh
# OR on Railway/Render: Click "Restart"
```

---

## ✅ Verification Steps

After recovery, verify the system is working correctly:

### 1. Check Startup Logs

Look for these messages within 45-60 seconds of startup:

```
✅ Using KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET for platform account
⏳ Waiting 5.0s before Kraken connection test (prevents nonce collisions)...
✅ Startup delay complete, testing Kraken connection...
Testing Kraken connection (MASTER)...
✅ KRAKEN PRO CONNECTED (MASTER)
   Balance: $XX.XX
```

### 2. Verify All Accounts Connected

Check for balance snapshot:

```
======================================================================
💰 USER BALANCE SNAPSHOT
======================================================================
   • Master: $XX.XX
      - KRAKEN: $XX.XX
   • Daivon: $XX.XX
      - KRAKEN: $XX.XX
   • Tania: $XX.XX
      - KRAKEN: $XX.XX

   🏦 TOTAL CAPITAL UNDER MANAGEMENT: $XXX.XX
======================================================================
```

### 3. Watch for Trading Cycles

Monitor logs for trading cycles:

```
🎯 COINBASE MASTER TRADING CYCLE #X
💰 Current balance: $XX.XX
📊 Mode: MASTER (full strategy execution)
```

### 4. Verify Copy Trading Engine

Check for copy engine startup:

```
🔄 Starting copy trade engine in MASTER_FOLLOW MODE...
   📋 Mode: MASTER_FOLLOW (mirror master trades)
   ✅ Copy trade engine started in ACTIVE MODE
```

### 5. Test a Trade (When It Happens)

When the master executes a trade, look for:

```
📡 MASTER EXIT/PROFIT-TAKING SIGNAL SENT
🔄 COPY TRADING TO X USERS
   ✅ TRADE COMPLETE | txid: XXXXX
📊 COPY TRADING SUMMARY
   Success: X/X
   Failed: 0/X
```

---

## 🔧 Troubleshooting Common Issues

### Issue: "Kraken connection failed"

**Symptoms**: Can't connect to Kraken, authentication errors

**Solutions**:
1. Verify API credentials are set correctly
2. Check API key has correct permissions:
   - Query Funds ✅
   - Query Open Orders & Trades ✅
   - Create & Modify Orders ✅
   - Cancel/Close Orders ✅
3. Ensure no extra spaces in credentials
4. Try regenerating API keys on Kraken

### Issue: "Copy trading not working"

**Symptoms**: Master trades but users don't copy

**Solutions**:
1. Check `COPY_TRADING_MODE=MASTER_FOLLOW` is set
2. Verify user API credentials are configured
3. Check logs for copy engine startup messages
4. Ensure user configs exist in `/config/users/`

### Issue: "Balance shows $0.00"

**Symptoms**: Account connected but balance is zero

**Solutions**:
1. Wait 45-60 seconds for balance fetch
2. Check API key has "Query Funds" permission
3. Verify you're looking at correct account/exchange
4. Check Kraken API status: https://status.kraken.com/

### Issue: "Nonce collision errors"

**Symptoms**: "Invalid nonce" or "nonce too low" errors

**Solutions**:
1. Restart the bot (clears nonce state)
2. Wait 10 seconds between restarts
3. Ensure only ONE instance of bot is running
4. Check `/data/kraken_nonce_*.txt` files aren't corrupted

### Issue: "No trades executing"

**Symptoms**: Bot runs but never places trades

**Solutions**:
1. Check entry blocking: `ENTRY_BLOCKING=false`
2. Verify minimum balance met ($10+ recommended)
3. Check position cap not full (max 8)
4. Review market conditions (may not have signals)
5. Check logs for "CONDITION PASSED" messages

---

## 📊 Expected Behavior After Recovery

### Startup Sequence (0-60 seconds)
```
1. Load configuration
2. Initialize broker connections
3. 5s delay for Kraken nonce coordination
4. Test Kraken connection (master)
5. Fetch account balances
6. Display balance snapshot
7. Start copy trade engine
8. Begin trading cycles (every 2.5 minutes)
```

### During Operation
- **Scanning**: Every 2.5 minutes across 732+ markets
- **Copy Trades**: Within 1-2 seconds of master execution
- **Position Monitoring**: Continuous P&L tracking
- **Profit-Taking**: Automatic at configured targets

### Success Indicators
- ✅ All accounts show positive balances
- ✅ Trading cycles running regularly
- ✅ Copy engine active and monitoring
- ✅ No authentication errors
- ✅ Trades executing when signals trigger

---

## 🚨 Emergency Procedures

### Emergency Stop All Trading

```bash
# Set environment variable
ENTRY_BLOCKING=true

# Restart bot
./start.sh
```

Or manually stop the bot process:
```bash
# Find process
ps aux | grep python | grep bot

# Kill it
kill <PID>
```

### Emergency Disable Copy Trading

```bash
# Set environment variable
COPY_TRADING_MODE=INDEPENDENT

# Restart bot
./start.sh
```

### Emergency Liquidate Positions

**Manual Method** (safest):
1. Log into Kraken.com
2. Go to Portfolio → Trade
3. Manually close positions

**Automated Method** (if available):
```bash
python emergency_liquidation.py
```

---

## 📝 Post-Recovery Checklist

After completing recovery, verify:

- [ ] All environment variables configured correctly
- [ ] Git is on correct branch/commit
- [ ] Bot starts without errors
- [ ] Kraken connections established (platform + users)
- [ ] Balance snapshot displays all accounts
- [ ] Copy trade engine started
- [ ] Trading cycles running
- [ ] No error messages in logs
- [ ] SUCCESS_STATE_2026_01_25.md exists
- [ ] REPOSITORY_CLEANUP_GUIDE.md exists

---

## 🔍 Diagnostic Commands

Run these commands to verify system health:

```bash
# Check current git state
git branch
git log --oneline -5
git status

# Verify key files exist
ls -la SUCCESS_STATE_2026_01_25.md
ls -la REPOSITORY_CLEANUP_GUIDE.md
ls -la README.md

# Check Python dependencies
pip freeze | grep -i kraken

# Test Kraken connection (if available)
python diagnose_kraken_trading.py

# Verify user configs
ls -la config/users/

# Check environment variables (partial - don't expose secrets!)
env | grep -i "KRAKEN\|COPY_TRADING" | sed 's/=.*/=***HIDDEN***/'
```

---

## 📞 Support Resources

### Documentation
- [SUCCESS_STATE_2026_01_25.md](SUCCESS_STATE_2026_01_25.md) - Current success state
- [COPY_TRADING_SETUP.md](COPY_TRADING_SETUP.md) - Copy trading guide
- [KRAKEN_TRADING_GUIDE.md](KRAKEN_TRADING_GUIDE.md) - Kraken setup
- [USER_MANAGEMENT.md](USER_MANAGEMENT.md) - User configuration
- [EMERGENCY_PROCEDURES.md](EMERGENCY_PROCEDURES.md) - Emergency actions

### Diagnostic Tools
```bash
python diagnose_kraken_trading.py     # Kraken diagnostics
python test_kraken_validation.py      # Validate setup
python test_copy_trading_requirements.py  # Test copy system
```

### Key Directories
- `/bot/` - Core trading code
- `/config/users/` - User account configs
- `/data/` - State persistence (nonce files, etc.)
- `/archive/` - Historical documentation

---

## ⚡ Quick Recovery (TL;DR)

**Fastest path back to working state:**

```bash
# 1. Get the code
git checkout copilot/update-readme-for-success-lock
git pull origin copilot/update-readme-for-success-lock

# 2. Verify environment variables (Railway/Render/Local)
# - KRAKEN_PLATFORM_API_KEY + SECRET
# - KRAKEN_USER_DAIVON_API_KEY + SECRET
# - KRAKEN_USER_TANIA_API_KEY + SECRET
# - COPY_TRADING_MODE=MASTER_FOLLOW

# 3. Restart
./start.sh

# 4. Verify (within 60 seconds)
# - Balance snapshot appears
# - All accounts connected
# - Copy engine started
# - Trading cycles begin
```

**Done!** You're back to the verified success state.

---

## 🎯 Success Metrics

You'll know recovery is successful when:

1. ✅ **Master Trading**: Kraken platform account executing trades
2. ✅ **User Copy Trading**: 2 users copying master trades (100% success rate)
3. ✅ **Profit-Taking**: All accounts taking profits on winning trades
4. ✅ **Risk Management**: 10% max risk caps enforced
5. ✅ **Balance Tracking**: Live balance fetching working
6. ✅ **Position Sizing**: Proportional sizing based on account balance

Match these metrics to the [SUCCESS_STATE_2026_01_25.md](SUCCESS_STATE_2026_01_25.md) benchmarks.

---

**Status**: 🟢 Recovery procedures verified and documented
**Last Tested**: January 25, 2026
**Confidence Level**: HIGH - Multiple recovery paths available
