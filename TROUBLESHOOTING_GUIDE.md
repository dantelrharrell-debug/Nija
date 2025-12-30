# NIJA Troubleshooting Guide

**Version**: 1.0  
**Date**: December 30, 2025  
**Purpose**: Comprehensive guide to diagnosing and fixing common NIJA bot issues

---

## Table of Contents

1. [Quick Diagnostics](#quick-diagnostics)
2. [Balance & API Issues](#balance--api-issues)
3. [Trading Issues](#trading-issues)
4. [Position Management Issues](#position-management-issues)
5. [Performance Issues](#performance-issues)
6. [Deployment Issues](#deployment-issues)
7. [Recovery Procedures](#recovery-procedures)

---

## Quick Diagnostics

### Is NIJA Working?

Run these quick checks in order:

```bash
# 1. Check if bot is running
python3 check_bot_status.py

# 2. Check balance detection
python3 test_v2_balance.py

# 3. Check recent activity
python3 check_if_selling_now.py

# 4. Check profitability status
python3 check_nija_profitability_status.py

# 5. Full diagnostic
python3 diagnose_profitability_now.py
```

### Expected vs Actual Behavior

| Check | Expected | If Not Working | Fix |
|-------|----------|----------------|-----|
| Bot Status | "Bot is running" | "Bot not found" | Restart with `./start.sh` |
| Balance | "$XX.XX USD" | "$0.00" | See [Balance Issues](#balance-issues) |
| Recent Activity | "Recent trades found" | "No recent activity" | See [Trading Issues](#trading-issues) |
| Profitability | "5/5 checks pass" | "X/5 checks fail" | See specific check that failed |

---

## Balance & API Issues

### Issue 1: Balance Shows $0.00

**Symptoms**:
- Bot reports $0.00 balance
- `test_v2_balance.py` shows 0
- But Coinbase web UI shows funds

**Causes**:
1. API credentials wrong/expired
2. Funds in wrong portfolio (Consumer vs Advanced Trade)
3. API permissions insufficient
4. Coinbase SDK compatibility issue

**Solutions**:

#### Step 1: Verify API Credentials

```bash
# Check .env file exists and has correct format
cat .env | grep COINBASE_API

# Should show:
# COINBASE_API_KEY="organizations/xxx/apiKeys/xxx"
# COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
```

**Fix if wrong**:
```bash
# Regenerate API key at https://portal.cloud.coinbase.com/access/api
# Update .env with new credentials
nano .env
# Restart bot
```

#### Step 2: Check Portfolio

```bash
# Check which portfolio holds your funds
python3 show_all_accounts.py

# Look for "DEFAULT" portfolio
# Funds must be in "Advanced Trade" or "DEFAULT" portfolio
```

**Fix if in wrong portfolio**:
```bash
# Transfer funds to Advanced Trade
python3 transfer_to_advanced_trade.py
```

#### Step 3: Verify API Permissions

Required permissions:
- ✅ View (read account data)
- ✅ Trade (place/cancel orders)
- ✅ Transfer (optional, for portfolio management)

**Fix permissions**:
1. Go to https://portal.cloud.coinbase.com/access/api
2. Edit API key
3. Enable View + Trade permissions
4. Save and update `.env` with new secret if regenerated

#### Step 4: SDK Compatibility Check

```bash
# Test if SDK is returning objects vs dicts
python3 check_tradable_balance.py

# Should show balance, not errors about 'Account' object
```

**Fix if SDK issue**:
```bash
# Update Coinbase SDK
pip install --upgrade coinbase-advanced-py

# Or restore from working commit (see README Recovery Guide)
git reset --hard <working-commit-hash>
```

---

### Issue 2: API Authentication Failed (401)

**Symptoms**:
- "401 Unauthorized" errors in logs
- "Invalid API key" messages
- Bot can't connect to Coinbase

**Causes**:
1. API key expired
2. API secret malformed (newlines broken)
3. Clock drift (time sync issue)
4. IP whitelist restrictions

**Solutions**:

#### Step 1: Regenerate API Key

```bash
# 1. Go to https://portal.cloud.coinbase.com/access/api
# 2. Delete old key
# 3. Create new key with View + Trade permissions
# 4. Download JSON credentials
# 5. Update .env file
```

#### Step 2: Fix API Secret Format

The API secret must have `\n` for newlines:

```bash
# WRONG (literal newlines):
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIKB...
-----END EC PRIVATE KEY-----"

# CORRECT (escaped newlines):
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIKB...\n-----END EC PRIVATE KEY-----\n"
```

#### Step 3: Check System Time

```bash
# Check if system time is accurate
date

# If wrong, sync time:
sudo ntpdate pool.ntp.org  # Linux
# Or check time sync in Railway/system settings
```

---

### Issue 3: Rate Limit Exceeded

**Symptoms**:
- "429 Too Many Requests" errors
- Bot slowing down or stopping
- "Rate limit exceeded" messages

**Causes**:
1. Scanning too many markets too fast
2. Too frequent balance checks
3. Multiple bot instances running

**Solutions**:

#### Step 1: Reduce Market Scan Frequency

```python
# In bot/trading_strategy.py or bot.py
time.sleep(15)  # Increase from 2-5 seconds to 15+ seconds
```

#### Step 2: Limit Market Scanning

```python
# In bot/trading_strategy.py
MARKET_SCAN_LIMIT = 50  # Reduce from 730+ to 50-100
```

#### Step 3: Check for Duplicate Bots

```bash
# Check if multiple bots running
ps aux | grep python | grep nija

# Kill duplicates (keep only one)
kill <process-id>
```

---

## Trading Issues

### Issue 4: No Trades Executing

**Symptoms**:
- Bot scanning markets but not trading
- "No trade signals found" in logs
- Balance sitting idle

**Causes**:
1. Filters too strict (no markets pass)
2. Balance below minimum
3. Position limit reached
4. Circuit breaker active
5. Market conditions poor

**Solutions**:

#### Step 1: Check Balance Minimum

```bash
# Check current balance
python3 check_balance_now.py

# Minimum thresholds:
# - $2 absolute minimum (very small positions, low profitability)
# - $10 recommended minimum for fee-adjusted profitability
# - $30+ optimal for consistent profits
```

**Fix if too low**:
```bash
# Deposit more funds OR
# Adjust minimum in bot/trading_strategy.py:
MIN_BALANCE_TO_TRADE_USD = 2.0  # Lower if needed for testing
```

#### Step 2: Check Filter Settings

```bash
# View current filter configuration
grep -A 5 "filter_agreement\|min_adx\|volume_threshold" bot/nija_apex_strategy_v71.py

# For NIJA to trade, markets need to pass 3/5 filters:
# - ADX > 20 (trending)
# - Volume > 50% of average
# - RSI in range (30-70)
# - Price above/below moving averages
# - Signal strength >= 3/5
```

**Fix if too strict**:
```python
# In bot/nija_apex_strategy_v71.py
# Line ~217 and ~295
signal = score >= 3  # Lower to 2 if needed (less strict)

# In bot/adaptive_growth_manager.py
# Adjust for your tier:
"min_adx": 15,  # Lower from 20 if needed
"volume_threshold": 0.4,  # Lower from 0.5 if needed
```

#### Step 3: Check Position Limit

```bash
# Check current positions
python3 check_current_positions.py

# Max positions per tier:
# Tier 1 ($10-50): 3-5 positions
# Tier 2 ($50-200): 5-8 positions
# Tier 3 ($200-1K): 8-10 positions
```

**Fix if at limit**:
```bash
# Close smallest positions
python3 close_dust_positions.py --threshold 5.00

# Or manually close via Coinbase
```

#### Step 4: Check Circuit Breaker

```bash
# Check if circuit breaker active
cat TRADING_LOCKED.conf

# Should NOT exist, or should be empty
# If exists with TRADING_DISABLED=true, bot won't trade
```

**Fix if locked**:
```bash
# Remove lock file (ONLY if you've reviewed and fixed issues)
rm TRADING_LOCKED.conf

# Or manually edit to set TRADING_DISABLED=false
```

---

### Issue 5: Too Many Small Trades (Fee Death)

**Symptoms**:
- Many trades showing $1-3 positions
- Winning trades but losing money
- Fees eating all profits

**Causes**:
1. Position sizing too small
2. Account balance too low
3. Not using fee-aware mode

**Solutions**:

#### Step 1: Check Fee-Aware Mode

```bash
# Verify fee-aware configuration loaded
grep "Fee-aware configuration loaded" bot/risk_manager.py

# Check if fee_aware_config.py exists
ls -la fee_aware_config.py
```

**Fix if missing**:
```python
# Create fee_aware_config.py with minimum position sizes
# See bot/fee_aware_config.py for reference
MIN_BALANCE_TO_TRADE = 10.0
```

#### Step 2: Increase Minimum Position Size

```python
# In bot/trading_strategy.py
MIN_POSITION_SIZE_USD = 5.0  # Increase from 1.0 to 5.0+

# In bot/risk_manager.py (calculate_position_size method)
MIN_ABSOLUTE_POSITION_SIZE = 5.0  # Increase minimum
```

#### Step 3: Switch to Lower-Fee Exchange

Consider using:
- **Binance**: 0.1% fees (14x better than Coinbase)
- **OKX**: 0.08% fees (17.5x better)
- **Kraken**: 0.16% fees (8.75x better)

```bash
# Enable multi-exchange support
# See MULTI_BROKER_ACTIVATION_GUIDE.md
```

---

### Issue 6: Trades Not Exiting at Profit Targets

**Symptoms**:
- Positions showing +2%, +3% but not selling
- Missing profit target exit logs
- Positions held for hours/days

**Causes**:
1. Position tracker not persisting entry prices
2. P&L calculation broken
3. Exit logic not being called
4. Threading deadlock

**Solutions**:

#### Step 1: Verify Position Tracking

```bash
# Check if positions.json exists and has data
cat positions.json

# Should show:
# {"SYMBOL-USD": {"entry_price": 12345.67, "size": 0.001, ...}}
```

**Fix if missing/empty**:
```bash
# Manually create with current positions
python3 sync_positions_from_coinbase.py

# Or restore from backup
git checkout HEAD -- positions.json
```

#### Step 2: Test P&L Calculation

```bash
# Run profitability test
python3 test_profitability_fix.py

# Should show:
# ✅ Position tracking working
# ✅ P&L calculation working
# ✅ Profit targets configured
```

**Fix if failing**:
```bash
# Restore from working state (see README Recovery Guide)
git checkout HEAD -- bot/position_tracker.py
git checkout HEAD -- bot/trading_strategy.py
```

#### Step 3: Check Exit Logic

```bash
# Verify profit targets are configured
grep "PROFIT_TARGETS" bot/trading_strategy.py

# Should show:
# PROFIT_TARGETS = [(3.0, ...), (2.0, ...), (1.0, ...), (0.5, ...)]
```

#### Step 4: Monitor for Deadlocks

```bash
# Check logs for threading warnings
tail -100 nija.log | grep -i "deadlock\|lock\|thread"

# If deadlock detected, restart bot
./restart_bot.sh
```

---

## Position Management Issues

### Issue 7: Stuck Positions (Won't Close)

**Symptoms**:
- Position showing in Coinbase but not closing
- "INVALID_SIZE_PRECISION" errors
- Sell orders failing

**Causes**:
1. Incorrect decimal precision for crypto
2. Position size too small (< minimum)
3. Insufficient funds/balance
4. API rate limiting

**Solutions**:

#### Step 1: Check Decimal Precision

Each crypto has specific decimal requirements:

```python
# From bot/broker_manager.py precision_map:
'BTC': 8 decimals
'ETH': 6 decimals  
'SOL': 4 decimals
'XRP': 2 decimals
'DOGE': 2 decimals
'SHIB': 0 decimals
```

**Fix if wrong**:
```bash
# Restore working broker_manager.py
git checkout HEAD -- bot/broker_manager.py

# Or manually update precision_map
```

#### Step 2: Check Minimum Order Sizes

```bash
# Each crypto has minimum order size on Coinbase
# If position < minimum, it won't close

# Close manually via Coinbase UI or
python3 force_sell_all_positions.py
```

#### Step 3: Emergency Position Close

```bash
# Force close all positions (use with caution)
python3 emergency_sell_all.py

# Or close specific position
python3 force_sell_all_positions.py --symbol BTC-USD
```

---

### Issue 8: Too Many Open Positions

**Symptoms**:
- 10, 15, 20+ positions open
- Violating tier position limits
- Capital spread too thin

**Causes**:
1. Position cap enforcer not running
2. Position limit set too high
3. Bot not closing positions

**Solutions**:

#### Step 1: Check Position Cap

```bash
# Verify position cap enforcer is active
grep "Position cap enforcer" logs/nija.log

# Should see:
# "✅ Position cap enforcer initialized (max: 8)"
```

**Fix if not running**:
```python
# In bot/trading_strategy.py
# Ensure position_cap_enforcer is imported and called
from position_cap_enforcer import enforce_position_cap

# In main loop:
enforce_position_cap(broker, max_positions=8)
```

#### Step 2: Force Close Excess Positions

```bash
# Close smallest positions to get under limit
python3 close_dust_positions.py --threshold 10.00

# Or force close to exactly 8 positions
python3 enforce_8_position_cap.py
```

#### Step 3: Adjust Position Limit

```python
# In bot/trading_strategy.py
MAX_POSITIONS_ALLOWED = 8  # Set to tier-appropriate limit
```

---

## Performance Issues

### Issue 9: Bot Running Slow

**Symptoms**:
- Long delays between scans (> 30 seconds)
- High CPU/memory usage
- Timeout errors

**Causes**:
1. Scanning too many markets
2. Inefficient API calls
3. Insufficient server resources
4. Network latency

**Solutions**:

#### Step 1: Reduce Market Scan

```python
# In bot/trading_strategy.py or bot.py
MARKET_SCAN_LIMIT = 50  # Reduce from 730

# Or use curated list
trading_pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', ...]  # Top 20
```

#### Step 2: Increase Scan Interval

```python
# In bot.py or main loop
time.sleep(15)  # Increase from 2-5 to 15+ seconds
```

#### Step 3: Optimize API Calls

```python
# Cache market data instead of fetching every time
# Use batch API calls where possible
# Implement rate limiting
```

#### Step 4: Upgrade Server Resources

```bash
# For Railway deployment:
# Upgrade to higher tier plan with more RAM/CPU

# For local deployment:
# Close other applications
# Use faster internet connection
```

---

### Issue 10: High Fee Impact

**Symptoms**:
- Fees consuming 20-50% of profits
- Small gains turning into losses
- Fee line item in trades very high

**Causes**:
1. Trading on high-fee exchange (Coinbase 1.4%)
2. Position sizes too small
3. Too many trades per day
4. Not using fee-aware mode

**Solutions**:

#### Step 1: Enable Fee-Aware Mode

```bash
# Verify fee_aware_config.py exists
cat fee_aware_config.py

# Should have:
# MIN_BALANCE_TO_TRADE = 10.0 (or higher)
# Position size minimums based on balance
```

#### Step 2: Increase Position Sizes

```python
# In bot/risk_manager.py
MIN_ABSOLUTE_POSITION_SIZE = 10.0  # Increase from 1.0
```

#### Step 3: Switch to Lower-Fee Exchange

**Fee Comparison**:
- Coinbase: 1.4% (0.6% + 0.8% spread)
- Binance: 0.1% (14x cheaper)
- OKX: 0.08% (17.5x cheaper)
- Kraken: 0.16% (8.75x cheaper)

```bash
# Set up Binance (recommended)
# Add to .env:
export BINANCE_API_KEY="your_key"
export BINANCE_API_SECRET="your_secret"

# Enable in bot/apex_live_trading.py
```

#### Step 4: Reduce Trade Frequency

```python
# In fee_aware_config.py
MAX_TRADES_PER_DAY = 20  # Reduce from 50+
```

---

## Deployment Issues

### Issue 11: Railway Deployment Failing

**Symptoms**:
- Deployment crashes on Railway
- "Build failed" errors
- Service not starting

**Causes**:
1. Requirements.txt missing dependencies
2. Dockerfile misconfigured
3. Environment variables not set
4. Python version mismatch

**Solutions**:

#### Step 1: Check Build Logs

```bash
# View Railway deployment logs
railway logs

# Look for:
# - Missing module errors
# - Python version errors
# - File not found errors
```

#### Step 2: Verify Requirements

```bash
# Check all dependencies listed
cat requirements.txt

# Test local install
pip install -r requirements.txt
```

#### Step 3: Check Environment Variables

Required in Railway:
- ✅ COINBASE_API_KEY
- ✅ COINBASE_API_SECRET  
- ✅ PORT (usually 5000)
- ✅ WEB_CONCURRENCY (set to 1)

#### Step 4: Verify Python Version

```bash
# Check runtime.txt
cat runtime.txt

# Should show:
# python-3.11

# Match local version
python --version
```

---

### Issue 12: Docker Build Failing

**Symptoms**:
- "docker build" fails
- Missing files in container
- Container exits immediately

**Solutions**:

#### Step 1: Clean Build

```bash
# Remove old images
docker rmi nija-bot

# Rebuild from scratch
docker build --no-cache -t nija-bot .
```

#### Step 2: Check Dockerfile

```dockerfile
# Verify Dockerfile has:
FROM python:3.11-slim
WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

#### Step 3: Test Container Locally

```bash
# Build and run
docker build -t nija-bot .
docker run --env-file .env nija-bot

# Check logs
docker logs <container-id>
```

---

## Recovery Procedures

### Emergency Recovery: Bot Not Working At All

**Step 1: Stop Everything**

```bash
# Stop bot if running
./EMERGENCY_STOP.sh

# Or manually
pkill -f "python.*nija"
pkill -f "python.*bot"
```

**Step 2: Create Trading Lock**

```bash
# Prevent bot from trading while you diagnose
echo "TRADING_DISABLED=true" > TRADING_LOCKED.conf
echo "ALLOW_NEW_POSITIONS=false" >> TRADING_LOCKED.conf
echo "EMERGENCY_STOP=true" >> TRADING_LOCKED.conf
```

**Step 3: Check Current State**

```bash
# Check balance
python3 check_balance_now.py

# Check positions
python3 check_current_positions.py

# Check recent activity
python3 check_if_selling_now.py
```

**Step 4: Restore from Known Good State**

```bash
# Find last working commit
git log --oneline | grep -i "working\|fix\|deploy" | head -10

# Restore to specific commit (see README Recovery Guide)
git reset --hard <commit-hash>

# Or restore specific files
git checkout HEAD -- bot/trading_strategy.py
git checkout HEAD -- bot/broker_manager.py
git checkout HEAD -- bot/risk_manager.py
```

**Step 5: Test Before Resuming**

```bash
# Test balance detection
python3 test_v2_balance.py

# Test profitability checks
python3 check_nija_profitability_status.py

# Should show 5/5 checks pass
```

**Step 6: Remove Trading Lock & Restart**

```bash
# Only if tests pass!
rm TRADING_LOCKED.conf

# Restart bot
./start.sh

# Monitor logs
tail -f nija.log
```

---

### Quick Recovery: Restore to Last Known Good State

**December 28, 2025 - P&L Tracking Fix** (Most Recent):
```bash
git log --oneline | grep "P&L tracking"
git reset --hard <commit-hash>
```

**December 27, 2025 - Filter Optimization**:
```bash
git log --oneline | grep "filter optimization"
git reset --hard <commit-hash>
```

**December 23, 2025 - v7.2 Profitability Upgrade**:
```bash
git log --oneline | grep "v7.2"
git reset --hard <commit-hash>
```

**See README.md Recovery Guide for detailed restore procedures**

---

## Getting Help

### Self-Service Resources

1. **README.md** - Main documentation, recovery guides
2. **CAPITAL_SCALING_PLAYBOOK.md** - Capital tier strategies
3. **EMERGENCY_PROCEDURES.md** - Emergency stop procedures
4. **Various *_GUIDE.md files** - Specific topics

### Diagnostic Commands Summary

```bash
# Balance issues
python3 test_v2_balance.py
python3 check_balance_now.py
python3 show_all_accounts.py

# Trading issues
python3 check_if_selling_now.py
python3 diagnose_profitability_now.py
python3 check_nija_profitability_status.py

# Position issues
python3 check_current_positions.py
python3 check_dust_positions.py
python3 sync_positions_from_coinbase.py

# Performance checks
python3 check_bot_status.py
python3 full_status_check.py
```

### Log Files to Check

```bash
# Main log
tail -100 nija.log

# Trade journal
cat trade_journal.jsonl | tail -20

# Position tracker
cat positions.json

# Git history
git log --oneline -20
```

---

**Last Updated**: December 30, 2025  
**Next Review**: Quarterly or after major issues  
**Maintained By**: NIJA Development Team
