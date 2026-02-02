# Heartbeat Trading & Trust Layer Guide

**Complete guide for deployment verification and transparent trade decision logging**

## Quick Start: Railway Deployment (10 minutes)

### Step 1: Set Environment Variables in Railway

```bash
# REQUIRED: Kraken Platform Credentials
KRAKEN_PLATFORM_API_KEY=<your-64-char-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-88-char-api-secret>

# REQUIRED: Trading Safety
LIVE_CAPITAL_VERIFIED=true

# REQUIRED: Heartbeat Verification (enable temporarily)
HEARTBEAT_TRADE=true
HEARTBEAT_TRADE_SIZE=5.50
HEARTBEAT_TRADE_INTERVAL=600
```

### Step 2: Deploy & Monitor Logs

Watch for heartbeat execution (~10 minutes):
```
❤️  HEARTBEAT TRADE ENABLED: $5.50 every 600s
...
❤️  HEARTBEAT TRADE EXECUTION
   ✅ Heartbeat trade #1 EXECUTED
```

### Step 3: Disable Heartbeat

Update Railway environment variable:
```bash
HEARTBEAT_TRADE=false
```

**That's it! Full details below.**

---

## Overview

This guide covers the new features added to NIJA for deployment verification and enhanced transparency:

1. **Heartbeat Trading** - Verify exchange connectivity with tiny test trades
2. **Trade Veto Logging** - Explicit logging of why trades were not executed
3. **User Status Banner** - Real-time status display with account information

## 1. Heartbeat Trading

### Purpose

Heartbeat trades are minimal-size test trades ($5.50) that verify:
- Exchange API credentials are working
- Order execution is functional
- Network connectivity is stable

### Use Cases

- **Deployment Verification**: Enable briefly after deploying to Railway/Render to confirm 1 trade executes
- **Health Monitoring**: Periodic verification that exchange connectivity remains stable
- **Credential Validation**: Verify API keys are valid and have proper permissions

### Configuration

Add to `.env` or set as environment variables:

```bash
# Enable heartbeat trading
HEARTBEAT_TRADE=true

# Trade size in USD (default: $5.50 - minimum viable)
HEARTBEAT_TRADE_SIZE=5.50

# Interval between heartbeat trades in seconds (default: 600 = 10 minutes)
HEARTBEAT_TRADE_INTERVAL=600
```

### How It Works

1. Bot checks if heartbeat is enabled and interval has elapsed
2. Selects a liquid market (prefers BTC-USD or ETH-USD)
3. Executes a tiny market buy order ($5.50)
4. Logs execution details and updates heartbeat counter
5. Next heartbeat won't execute until interval elapses

### Verification Process

**Step 1: Enable Heartbeat**
```bash
# In Railway/Render environment variables:
HEARTBEAT_TRADE=true
```

**Step 2: Deploy and Monitor Logs**
```
❤️  HEARTBEAT TRADE ENABLED: $5.50 every 600s
...
❤️  HEARTBEAT TRADE EXECUTION
   Symbol: BTC-USD
   Size: $5.50
   Broker: KRAKEN
   Purpose: Verify connectivity & order execution
   ✅ Heartbeat trade #1 EXECUTED
   Order ID: ABC123
   Status: filled
```

**Step 3: Verify Trade Executed**
Check exchange transaction history for the small order.

**Step 4: Disable Heartbeat**
```bash
# After confirming execution:
HEARTBEAT_TRADE=false
```

### Important Notes

⚠️ **Production Usage**:
- Enable ONLY for verification, then disable
- Each heartbeat costs money (trade fees)
- Not intended for continuous operation in production
- **RECOMMENDED**: Auto-disable after verifying 1-3 successful trades

✅ **Best Practice**:
- Enable after deployment
- Wait for 1-3 successful trades (10-30 minutes)
- Disable immediately after verification
- Re-enable only if you suspect connectivity issues

💡 **Auto-Disable Recommendation**:
While the bot won't auto-disable heartbeat, you should:
1. Set a calendar reminder to disable after 30 minutes
2. Or monitor logs and manually disable after seeing heartbeat execution
3. Consider heartbeat as a temporary diagnostic tool, not a permanent feature

## 2. Trade Veto Logging

### Purpose

Provides transparent logging of why the bot decided NOT to execute a trade. This builds trust and helps diagnose trading issues.

### What Gets Logged

Every time a trade is vetoed (blocked), the bot logs:
- **Reason**: Explicit explanation (e.g., "KRAKEN balance $8.50 < $10.00 minimum")
- **Broker**: Which exchange was checked
- **Context**: Balance, connection status, trading mode

### Example Veto Logs

```
🚫 TRADE VETO: KRAKEN not connected
   Reason: Exchange API connection failed
   
🚫 TRADE VETO: KRAKEN in EXIT-ONLY mode
   Reason: No new positions allowed (exit only)
   
🚫 TRADE VETO: KRAKEN balance $8.50 < $10.00 minimum
   Reason: Insufficient balance for minimum trade size
   
🚫 TRADE VETO: KRAKEN balance fetch failed: timeout or error
   Reason: Could not verify account balance
```

### Veto Session Tracking

The bot tracks vetoed trades per session:
```
📊 Vetoed Trades (Session): 12
📋 Last Veto Reason: KRAKEN balance $8.50 < $10.00 minimum
```

### Benefits

1. **Transparency**: Know exactly why bot isn't trading
2. **Debugging**: Quickly identify configuration issues
3. **Trust**: Explicit reasons build confidence in bot behavior

## 3. User Status Banner

### Purpose

Displays current account status at the start of each trading cycle, providing real-time visibility into:
- Account balance
- Active positions
- Trading status (active/vetoed)
- Heartbeat status

### Example Status Banner

```
======================================================================
📊 USER STATUS BANNER
======================================================================
   💰 KRAKEN Balance: $127.50
   📈 Active Positions: 3
   ✅ Trading Status: ACTIVE
   ❤️  Heartbeat: Last trade 245s ago (1 total)
======================================================================
```

When trades are vetoed:
```
======================================================================
📊 USER STATUS BANNER
======================================================================
   💰 KRAKEN Balance: $8.50
   📈 Active Positions: 0
   🚫 Trading Status: VETOED
   📋 Last Veto Reason: KRAKEN balance $8.50 < $10.00 minimum
   📊 Vetoed Trades (Session): 5
======================================================================
```

### When It Displays

- At the start of each trading cycle (every 2.5 minutes)
- After heartbeat trade execution
- When trading mode changes

## Railway Deployment

### Step 1: Set Environment Variables

In Railway dashboard, add:

```
KRAKEN_PLATFORM_API_KEY=<your-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-api-secret>
HEARTBEAT_TRADE=true
HEARTBEAT_TRADE_SIZE=5.50
HEARTBEAT_TRADE_INTERVAL=600
LIVE_CAPITAL_VERIFIED=true
```

### Step 2: Deploy

Railway will automatically:
1. Build from Dockerfile
2. Run `start.sh`
3. Connect to Kraken
4. Display status banner
5. Execute heartbeat trade (if enabled)

### Step 3: Monitor Logs

Watch Railway logs for:
```
✅ KRAKEN (Platform) - PRIMARY BROKER:
   ✅ Configured (Key: 64 chars, Secret: 88 chars)

❤️  HEARTBEAT TRADE ENABLED: $5.50 every 600s

📊 USER STATUS BANNER
   💰 KRAKEN Balance: $150.00
   ✅ Trading Status: ACTIVE
```

### Step 4: Verify and Disable Heartbeat

Once you see:
```
❤️  HEARTBEAT TRADE EXECUTION
   ✅ Heartbeat trade #1 EXECUTED
```

Update environment variable:
```
HEARTBEAT_TRADE=false
```

Railway will automatically redeploy with heartbeat disabled.

## Troubleshooting

### Heartbeat Not Executing

**Symptoms**: No heartbeat trade after 10 minutes

**Checks**:
1. Verify `HEARTBEAT_TRADE=true` in environment
2. Check account balance >= `HEARTBEAT_TRADE_SIZE`
3. Verify broker is connected (check status banner)
4. Look for veto logs explaining why trade was blocked

### Continuous Vetos

**Symptoms**: Status shows "VETOED" every cycle

**Common Causes**:
1. **Insufficient Balance**: Fund account above minimum ($10 for Kraken)
2. **API Credentials**: Verify `KRAKEN_PLATFORM_API_KEY` and `SECRET` are set correctly
3. **EXIT-ONLY Mode**: Check if broker is in exit-only mode (prevents new trades)
4. **Connection Issues**: Verify network connectivity to exchange

**Solution**: Check veto reason in status banner, address the specific issue.

### Status Banner Not Displaying

**Symptoms**: No status banner in logs

**Checks**:
1. Verify bot is running (check Railway/Render logs)
2. Look for error messages during startup
3. Check that `trading_strategy.py` imported successfully

## Security Notes

⚠️ **API Key Security**:
- Never commit `.env` file to version control
- Use Railway/Render environment variables for secrets
- Kraken API keys should have:
  - ✅ Query Funds
  - ✅ Query Orders & Trades
  - ✅ Create & Modify Orders
  - ❌ Do NOT enable "Withdraw Funds"

⚠️ **Heartbeat Cost**:
- Each heartbeat costs trading fees (~0.26% on Kraken)
- On $5.50 trade: ~$0.014 per heartbeat
- Disable after verification to avoid unnecessary fees

## Summary

1. **Heartbeat Trading**: Use for deployment verification, then disable
2. **Trade Veto Logging**: Automatic - provides transparency on trading decisions
3. **Status Banner**: Automatic - displays account status each cycle

These features enhance trust and transparency in NIJA's autonomous trading operations.
