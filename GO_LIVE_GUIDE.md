# NIJA Go Live Guide

## Overview

This guide walks you through the process of safely transitioning NIJA from DRY_RUN mode to LIVE trading mode. The `go_live.py` script automates all pre-flight checks to ensure your system is ready for live trading.

**Primary Broker:** Kraken (cryptocurrency trading)  
**Secondary Broker:** Coinbase (optional, disabled by default)

## Prerequisites

Before going live, ensure you have:

1. ✅ **Tested in DRY_RUN mode** - Run the bot in simulation mode first
2. ✅ **Kraken API credentials configured** - Platform and user accounts set up in `.env`
3. ✅ **Risk settings validated** - Position sizes, stop losses, etc. are appropriate
4. ✅ **Observability dashboard accessible** - Monitor system health in real-time
5. ✅ **Emergency procedures understood** - Know how to stop trading if needed

## Kraken Configuration Steps

### 1. Configure Kraken Platform Account (Required)

The platform account is NIJA's primary trading account on Kraken.

**Get API Credentials:**
1. Go to https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable "Withdraw Funds"
4. Copy the API Key and API Secret

**Configure in `.env`:**
```bash
KRAKEN_PLATFORM_API_KEY=your_platform_api_key_here
KRAKEN_PLATFORM_API_SECRET=your_platform_api_secret_here
```

**Verify Connection:**
```bash
python go_live.py --check
```

Look for "✅ Kraken platform account connection successful"

### 2. Configure Individual User Accounts (Optional)

User accounts allow multiple people to trade independently using NIJA's strategy.

**For each user (e.g., Daivon, Tania Gilbert):**

1. Create API credentials on their Kraken account (same process as platform account)
2. Add to `.env` following the pattern:
   ```bash
   # User: Daivon Frazier
   KRAKEN_USER_DAIVON_API_KEY=daivon_api_key_here
   KRAKEN_USER_DAIVON_API_SECRET=daivon_api_secret_here
   
   # User: Tania Gilbert
   KRAKEN_USER_TANIA_API_KEY=tania_api_key_here
   KRAKEN_USER_TANIA_API_SECRET=tania_api_secret_here
   ```

3. Configure user settings in `config/users/retail_kraken.json` or `config/users/investor_kraken.json`

**Pattern for Additional Users:**
```bash
KRAKEN_USER_{FIRSTNAME}_API_KEY=
KRAKEN_USER_{FIRSTNAME}_API_SECRET=
```

Where `{FIRSTNAME}` is the first name in UPPERCASE from the user_id in the user config JSON.

### 3. Set LIVE_CAPITAL_VERIFIED=true

This is the master safety switch that enables live trading:

```bash
# In .env file or environment
LIVE_CAPITAL_VERIFIED=true
```

⚠️ **IMPORTANT:** Only set this to `true` when you're ready to trade with real money.

## Quick Start

### Step 1: Check Current Status

First, check the current trading mode status:

```bash
python go_live.py --status
```

This shows:
- Current trading mode (DRY_RUN, LIVE, MONITOR, etc.)
- Environment variable settings
- Emergency stop status

### Step 2: Run Pre-Flight Checks

Run all pre-flight checks to validate system readiness:

```bash
python go_live.py --check
```

This validates:
1. ✅ DRY_RUN_MODE is disabled
2. ✅ LIVE_CAPITAL_VERIFIED can be enabled
3. ✅ All brokers show green (healthy)
4. ✅ Kraken platform account configured and connected
5. ✅ Kraken user accounts configured (if any)
6. ✅ No adoption failures
7. ✅ No halted threads
8. ✅ Capital safety thresholds satisfied
9. ✅ Multi-account isolation healthy
10. ✅ Recovery checks operational
11. ✅ API credentials configured
12. ✅ No emergency stops active

**Expected Output:**
- ✅ **All checks pass** → Proceed to Step 3
- ❌ **Critical failures** → Fix issues and re-run checks

### Step 3: Activate Live Mode

Once all checks pass, activate live mode:

```bash
python go_live.py --activate
```

This will:
1. Run all pre-flight checks again
2. Verify all requirements are met
3. Display final confirmation
4. Provide monitoring schedule and key metrics
5. Provide instructions to start the bot

### Step 4: Start the Bot in Live Mode

After activation confirms readiness, configure your environment and start the bot:

```bash
# Ensure these are set in your .env file
DRY_RUN_MODE=false
LIVE_CAPITAL_VERIFIED=true

# Start the bot
./start.sh
```

Or deploy to Railway/production:
```bash
# Railway will use .env file automatically
railway up
```

## Monitoring Schedule (First 24 Hours)

### First 30 Minutes: Continuous Monitoring

Watch for these critical indicators:

1. **Position Adoption** (100% success rate expected)
   - Check logs for "Position adopted successfully"
   - Verify no adoption failures

2. **Tier Floor Enforcement** (no trades below minimum)
   - Verify trade sizes meet tier minimums
   - Check that small trades are rejected

3. **Forced Cleanup Execution** (should run periodically)
   - Look for cleanup logs
   - Verify dust positions are cleaned up

4. **Risk Management** (thresholds respected)
   - Confirm risk per trade matches tier config
   - Check stop losses are placed correctly

5. **User Account Independence** (no trade copying)
   - Verify each account evaluates markets independently
   - Check that trades are not duplicated across accounts

### After 30 Minutes: Hourly Checks (for 24 hours)

Monitor these metrics every hour:

- **Position Status:** Open positions and P&L
- **User Account Performance:** Each account's independent performance
- **API Rate Limiting:** No rate limit errors
- **Broker Health:** All brokers remain green
- **Capital Allocation:** Proper distribution across accounts

## Detailed Check Descriptions

### 1. DRY_RUN Mode Check
**Purpose:** Ensures simulation mode is disabled  
**Critical:** Yes  
**Remediation:** Set `DRY_RUN_MODE=false` in `.env`

### 2. Live Capital Verification
**Purpose:** Confirms live trading is explicitly enabled  
**Critical:** Yes  
**Remediation:** Set `LIVE_CAPITAL_VERIFIED=true` in `.env`

### 3. Broker Health Check
**Purpose:** Validates all brokers are operational  
**Critical:** Yes (failed brokers), Warning (degraded brokers)  
**Remediation:** 
- Check broker status pages (Kraken, Coinbase, etc.)
- Verify API credentials
- Test connectivity manually
- Review observability dashboard

### 4. Kraken Platform Account Check
**Purpose:** Validates Kraken platform account credentials are configured  
**Critical:** Yes  
**Remediation:**
- Set `KRAKEN_PLATFORM_API_KEY` and `KRAKEN_PLATFORM_API_SECRET` in `.env`
- Alternative: Set legacy `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`
- Verify permissions: Query Funds, Orders, Create/Modify/Cancel Orders
- Do NOT enable "Withdraw Funds" permission

### 5. Kraken User Accounts Check
**Purpose:** Confirms user account credentials for multi-user trading  
**Critical:** No (Informational)  
**Remediation:**
- Optional: Add user credentials following pattern `KRAKEN_USER_{FIRSTNAME}_API_KEY`
- Each user needs their own Kraken API credentials
- Configure in `config/users/retail_kraken.json` or `investor_kraken.json`

### 6. Kraken Platform Connection
**Purpose:** Tests actual connection to Kraken API  
**Critical:** Yes (if credentials configured), Warning (if broker not initialized)  
**Remediation:**
- Verify API credentials are correct
- Check Kraken API status at https://status.kraken.com
- Test connectivity manually
- Ensure broker is initialized in broker_manager

### 7. Adoption Failures Check
**Purpose:** Detects user onboarding/authentication issues  
**Critical:** No (Warning only)  
**Remediation:**
- Review observability dashboard
- Check API credential validity
- Verify user onboarding flow

### 8. Trading Threads Check
**Purpose:** Ensures no trading threads are halted or deadlocked  
**Critical:** Yes  
**Remediation:**
- Check application logs for exceptions
- Restart halted threads
- Investigate deadlock causes
- Review thread status in dashboard

### 9. Capital Safety Thresholds
**Purpose:** Validates capital reservation and safety buffers  
**Critical:** Yes  
**Remediation:**
- Ensure `bot/capital_reservation_manager.py` is available
- Verify safety buffer configuration (default: 20%)
- Confirm minimum free capital settings

### 10. Multi-Account Isolation
**Purpose:** Confirms account isolation system is operational  
**Critical:** Yes  
**Remediation:**
- Ensure `bot/account_isolation_manager.py` is available
- Verify isolation configuration
- Test account separation

### 11. Recovery Mechanisms
**Purpose:** Validates circuit breakers and recovery systems  
**Critical:** Yes  
**Remediation:**
- Ensure recovery systems are configured
- Verify circuit breaker thresholds (default: 5 failures, 300s timeout)
- Test recovery flows

### 12. Emergency Stop Check
**Purpose:** Ensures no emergency stop file exists  
**Critical:** Yes  
**Remediation:** Remove `EMERGENCY_STOP` file if present

## Environment Configuration

### Required Environment Variables

Create or update your `.env` file:

```bash
# Trading Mode Control
DRY_RUN_MODE=false                    # Disable simulation mode
LIVE_CAPITAL_VERIFIED=true            # Enable live trading
APP_STORE_MODE=false                  # Disable app store demo mode

# Kraken API Credentials (REQUIRED for live trading)
# Platform Account (Primary Trading Account)
KRAKEN_PLATFORM_API_KEY=your_platform_key
KRAKEN_PLATFORM_API_SECRET=your_platform_secret

# User Accounts (Optional - for multi-user trading)
KRAKEN_USER_DAIVON_API_KEY=daivon_key
KRAKEN_USER_DAIVON_API_SECRET=daivon_secret

KRAKEN_USER_TANIA_API_KEY=tania_key
KRAKEN_USER_TANIA_API_SECRET=tania_secret

# Add more users following the pattern:
# KRAKEN_USER_{FIRSTNAME}_API_KEY=
# KRAKEN_USER_{FIRSTNAME}_API_SECRET=

# Optional: Coinbase (Secondary Broker - Disabled by Default)
# COINBASE_API_KEY=your_coinbase_key
# COINBASE_API_SECRET=your_coinbase_secret

# Safety Settings (optional, defaults provided)
SAFETY_BUFFER_PCT=0.20                # 20% capital safety buffer
MIN_FREE_CAPITAL_USD=5.0              # Minimum $5 free capital
```

### Safety Lock Behavior

The system uses a **safety-first** approach:

1. **DRY_RUN_MODE=true** → Always takes precedence (forces simulation)
2. **LIVE_CAPITAL_VERIFIED=false** → Trading disabled (monitor mode)
3. **LIVE_CAPITAL_VERIFIED=true** + **DRY_RUN_MODE=false** → LIVE trading

## Observability Dashboard

### Accessing the Dashboard

Open the production observability dashboard to monitor system health:

```bash
# Option 1: Direct file access
open NIJA_PRODUCTION_OBSERVABILITY_DASHBOARD.html

# Option 2: Via HTTP server
python3 -m http.server 8000
# Then visit: http://localhost:8000/NIJA_PRODUCTION_OBSERVABILITY_DASHBOARD.html
```

### Dashboard Features

The dashboard shows real-time status of:

- **Adoption Failures** (🚨 RED if detected)
- **Broker Health** (🚨 RED for failed, ⚠️ ORANGE for degraded)
- **Trading Thread Status** (🚨 RED for halted)
- **Capital Safety Metrics**
- **Auto-refresh every 5 seconds**

### What to Monitor

Once live, monitor:

1. **Broker Health** - All brokers should show green
2. **Trading Threads** - No halted threads
3. **Position Sizes** - Within configured limits
4. **Stop Losses** - Always active
5. **Capital Usage** - Respecting safety buffers

## Emergency Procedures

### Immediate Stop

If you need to stop trading immediately:

#### Method 1: Emergency Stop File
```bash
# Create emergency stop file
touch EMERGENCY_STOP

# Bot will detect this and disable trading
# To resume, delete the file:
rm EMERGENCY_STOP
```

#### Method 2: Environment Variable
```bash
# Set emergency stop environment variable
export DRY_RUN_MODE=true

# Restart the bot
./start.sh
```

#### Method 3: Kill the Process
```bash
# Find the bot process
ps aux | grep trading_strategy

# Kill it
kill <process_id>
```

### Disable Live Mode

To return to monitor/simulation mode:

```bash
# Update .env file
export LIVE_CAPITAL_VERIFIED=false
export DRY_RUN_MODE=true  # Optional: enable simulation

# Restart the bot
./start.sh
```

## Troubleshooting

### Check Fails: "No broker health data available"

**Cause:** Health check system not initialized or no brokers configured

**Solution:**
1. Ensure bot has been started at least once
2. Verify broker configurations in `bot/broker_configs/`
3. Check that health check manager is initialized in startup code

### Check Fails: "API credentials not found"

**Cause:** Environment variables not set

**Solution:**
1. Create `.env` file in repository root
2. Add API credentials (see Environment Configuration section)
3. Ensure `.env` is loaded: `source .env`

### Check Fails: "Halted threads detected"

**Cause:** Trading threads are deadlocked or stopped

**Solution:**
1. Check application logs for exceptions
2. Review thread status in observability dashboard
3. Restart the bot
4. Investigate root cause (network issues, API errors, etc.)

### Check Fails: "Failed brokers detected"

**Cause:** Broker API connectivity issues

**Solution:**
1. Check broker status pages (Coinbase, Kraken, etc.)
2. Verify API credentials are valid
3. Test API connectivity manually
4. Check network connectivity
5. Review API rate limits

### All Checks Pass but Bot Won't Trade

**Cause:** Bot may be in monitor mode or position limits reached

**Solution:**
1. Verify `LIVE_CAPITAL_VERIFIED=true` in environment
2. Check position limits in configuration
3. Ensure capital is available
4. Review bot logs for entry conditions

## Best Practices

### Before Going Live

1. **Test Thoroughly**
   - Run in DRY_RUN mode for at least 1 week
   - Validate entry/exit logic
   - Verify risk management

2. **Start Small**
   - Use minimal capital initially
   - Small position sizes
   - Gradually scale up

3. **Monitor Actively**
   - Keep observability dashboard open
   - Check positions regularly
   - Review logs for errors

4. **Document Settings**
   - Save configuration backup
   - Document risk parameters
   - Record initial capital

### After Going Live

1. **Monitor First Trades**
   - Watch first 5-10 trades closely
   - Verify execution quality
   - Confirm stop losses work

2. **Daily Checks**
   - Review P&L daily
   - Check for errors in logs
   - Verify capital safety buffers

3. **Weekly Reviews**
   - Analyze strategy performance
   - Review risk metrics
   - Adjust parameters if needed

## Advanced Usage

### Custom Safety Buffers

Override default safety settings:

```bash
# In .env file
SAFETY_BUFFER_PCT=0.25              # 25% safety buffer
MIN_FREE_CAPITAL_USD=10.0           # Minimum $10 free
MAX_POSITION_SIZE_PCT=0.15          # Max 15% per position
```

### Multiple Accounts

For multi-account deployments:

```bash
# Account isolation is automatic
# Each account has:
# - Separate API credentials
# - Independent capital tracking
# - Isolated failure handling
# - Individual circuit breakers
```

### Custom Monitoring

Set up custom alerts:

```python
from bot.health_check import get_health_manager

health_mgr = get_health_manager()

# Check critical status programmatically
status = health_mgr.get_critical_status()

if status['broker_health']['status'] == 'failed':
    # Send alert (email, Slack, PagerDuty, etc.)
    send_alert("Broker failure detected!")
```

## Support

For issues or questions:

1. Check this guide first
2. Review troubleshooting section
3. Check system logs in `logs/` directory
4. Run diagnostics: `python go_live.py --check`
5. Review observability dashboard
6. Check GitHub issues

## Safety Reminders

⚠️ **IMPORTANT SAFETY NOTICES:**

1. **Real Money** - Live mode trades with real capital
2. **Market Risk** - Cryptocurrency markets are highly volatile
3. **API Limits** - Respect exchange rate limits
4. **Monitor Actively** - Don't run unattended initially
5. **Emergency Stop** - Know how to stop trading immediately
6. **Start Small** - Begin with minimal capital
7. **Test First** - Always test in DRY_RUN mode first
8. **Backup Config** - Save configuration before changes

## Troubleshooting Common Kraken Issues

### Issue: "Kraken platform account credentials not found"

**Cause:** Missing or incorrectly named environment variables

**Solution:**
1. Check your `.env` file has:
   ```bash
   KRAKEN_PLATFORM_API_KEY=your_key
   KRAKEN_PLATFORM_API_SECRET=your_secret
   ```
2. Ensure no extra spaces or quotes
3. Restart the application after changing `.env`
4. Verify with: `python go_live.py --check`

### Issue: "Unable to connect to Kraken platform account"

**Cause:** Invalid API credentials or network issues

**Solution:**
1. Verify API credentials at https://www.kraken.com/u/security/api
2. Check API key has correct permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
3. Check Kraken API status at https://status.kraken.com
4. Test connectivity: `curl -v https://api.kraken.com/0/public/Time`
5. Ensure firewall/VPN not blocking Kraken API

### Issue: "Kraken broker not initialized in broker manager"

**Cause:** Broker manager not started or Kraken broker not added

**Solution:**
1. This is expected if checking before starting the bot
2. Start the bot first: `./start.sh`
3. Or deploy to production and check after startup
4. If broker still not initialized, check logs for broker initialization errors

### Issue: User account trades are duplicated

**Cause:** Incorrect user configuration or copy trading enabled

**Solution:**
1. Check user config in `config/users/retail_kraken.json`
2. Ensure `"independent_trading": true` is set
3. Set `"copy_from_master": false` if present
4. Verify `TRADING_MODE=independent` in `.env`
5. Each user should have their own API credentials

### Issue: Trades below tier floor being rejected

**Cause:** Expected behavior - tier floor enforcement working correctly

**Solution:**
1. This is correct behavior - small trades are filtered for profitability
2. Check tier minimums:
   - STARTER ($50-$99): Min $10 visible trades
   - SAVER ($100-$249): Min $15 visible trades
   - INVESTOR ($250-$999): Min $20 visible trades
3. Adjust account balance to meet tier requirements
4. Or accept that very small trades won't be executed

### Issue: "LIVE_CAPITAL_VERIFIED is not enabled"

**Cause:** Safety lock preventing live trading

**Solution:**
1. This is intentional - you must explicitly enable live trading
2. Only set `LIVE_CAPITAL_VERIFIED=true` when ready to trade real money
3. Update `.env` file and restart
4. Re-run: `python go_live.py --check`

### Issue: Position adoption failures on startup

**Cause:** Existing positions not recognized or API issues

**Solution:**
1. Check logs for specific adoption error messages
2. Verify API credentials have "Query Open Orders" permission
3. Clear orphaned positions manually if needed
4. Restart bot to retry adoption
5. Check observability dashboard for adoption metrics

## Version History

- **Version 2.0** (February 17, 2026)
  - Added Kraken platform and multi-user account support
  - Updated monitoring schedule with 24-hour guidance
  - Added comprehensive Kraken configuration steps
  - Added troubleshooting section for common Kraken issues

- **Version 1.0** (February 17, 2026)
  - Initial go-live automation
  - Comprehensive pre-flight checks
  - Observability integration
  - Emergency procedures documented

---

**Ready to Go Live?**

```bash
# Step 1: Check status
python go_live.py --status

# Step 2: Run checks
python go_live.py --check

# Step 3: Activate (after checks pass)
python go_live.py --activate

# Step 4: Start trading
./start.sh
```

**Trade safely!** 🚀
