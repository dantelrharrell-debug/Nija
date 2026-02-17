# NIJA Go Live Guide

## Overview

This guide walks you through the process of safely transitioning NIJA from DRY_RUN mode to LIVE trading mode. The `go_live.py` script automates all pre-flight checks to ensure your system is ready for live trading.

## Prerequisites

Before going live, ensure you have:

1. ✅ **Tested in DRY_RUN mode** - Run the bot in simulation mode first
2. ✅ **API credentials configured** - Coinbase API keys set up in `.env`
3. ✅ **Risk settings validated** - Position sizes, stop losses, etc. are appropriate
4. ✅ **Observability dashboard accessible** - Monitor system health in real-time
5. ✅ **Emergency procedures understood** - Know how to stop trading if needed

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
4. ✅ No adoption failures
5. ✅ No halted threads
6. ✅ Capital safety thresholds satisfied
7. ✅ Multi-account isolation healthy
8. ✅ Recovery checks operational
9. ✅ API credentials configured
10. ✅ No emergency stops active

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
4. Provide instructions to start the bot

### Step 4: Start the Bot in Live Mode

After activation confirms readiness, configure your environment and start the bot:

```bash
# Update .env file
export DRY_RUN_MODE=false
export LIVE_CAPITAL_VERIFIED=true

# Start the bot
./start.sh
```

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
- Check broker status pages (Coinbase, Kraken, etc.)
- Verify API credentials
- Test connectivity manually
- Review observability dashboard

### 4. Adoption Failures Check
**Purpose:** Detects user onboarding/authentication issues  
**Critical:** No (Warning only)  
**Remediation:**
- Review observability dashboard
- Check API credential validity
- Verify user onboarding flow

### 5. Trading Threads Check
**Purpose:** Ensures no trading threads are halted or deadlocked  
**Critical:** Yes  
**Remediation:**
- Check application logs for exceptions
- Restart halted threads
- Investigate deadlock causes
- Review thread status in dashboard

### 6. Capital Safety Thresholds
**Purpose:** Validates capital reservation and safety buffers  
**Critical:** Yes  
**Remediation:**
- Ensure `bot/capital_reservation_manager.py` is available
- Verify safety buffer configuration (default: 20%)
- Confirm minimum free capital settings

### 7. Multi-Account Isolation
**Purpose:** Confirms account isolation system is operational  
**Critical:** Yes  
**Remediation:**
- Ensure `bot/account_isolation_manager.py` is available
- Verify isolation configuration
- Test account separation

### 8. Recovery Mechanisms
**Purpose:** Validates circuit breakers and recovery systems  
**Critical:** Yes  
**Remediation:**
- Ensure recovery systems are configured
- Verify circuit breaker thresholds (default: 5 failures, 300s timeout)
- Test recovery flows

### 9. API Credentials Check
**Purpose:** Confirms exchange API credentials are configured  
**Critical:** Yes  
**Remediation:**
- Add credentials to `.env` file:
  ```
  COINBASE_API_KEY=your_api_key_here
  COINBASE_API_SECRET=your_api_secret_here
  COINBASE_PEM_CONTENT=your_pem_content_here
  ```

### 10. Emergency Stop Check
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

# Coinbase API Credentials (REQUIRED for live trading)
COINBASE_API_KEY=your_api_key
COINBASE_API_SECRET=your_api_secret
COINBASE_PEM_CONTENT=your_pem_content

# Optional: Additional Exchanges
KRAKEN_API_KEY=your_kraken_key
KRAKEN_API_SECRET=your_kraken_secret

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

## Version History

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
