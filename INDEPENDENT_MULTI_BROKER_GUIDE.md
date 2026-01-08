# NIJA Independent Multi-Broker Trading Guide

## Overview

NIJA now supports **independent multi-broker trading**, where each connected and funded brokerage operates in complete isolation. This architecture ensures that failures in one broker don't affect trading on other brokers.

## Key Features

### ✅ Error Isolation
- Each broker runs in its own thread
- Failures are contained to the affected broker
- Other brokers continue trading normally
- No cascade failures

### ✅ Automatic Funded Broker Detection
- Automatically detects brokers with sufficient balance (≥ $10)
- Only funded brokers participate in trading
- Underfunded brokers are skipped

### ✅ Independent Health Monitoring
- Per-broker health tracking
- Error counts and success rates
- Automatic recovery on transient failures
- Detailed status logging

### ✅ Graceful Degradation
- Bot continues operating even if some brokers fail
- Automatic retry logic for failed brokers
- Clean shutdown of all trading threads

## Supported Brokers

NIJA supports independent trading on:
- **Coinbase Advanced Trade** (Crypto)
- **Kraken Pro** (Crypto)
- **OKX** (Crypto)
- **Binance** (Crypto)
- **Alpaca** (Stocks)

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────┐
│           NIJA Bot Main Process                 │
│                                                 │
│  ┌────────────────────────────────────────┐   │
│  │  Independent Broker Trader Manager      │   │
│  └────────────────────────────────────────┘   │
│                      │                          │
│      ┌───────────────┼───────────────┐         │
│      │               │               │          │
│  ┌───▼────┐     ┌───▼────┐     ┌───▼────┐    │
│  │ Thread │     │ Thread │     │ Thread │     │
│  │Coinbase│     │ Kraken │     │  OKX   │     │
│  │        │     │        │     │        │     │
│  │  🔒    │     │  🔒    │     │  🔒    │     │
│  │Isolated│     │Isolated│     │Isolated│     │
│  └────────┘     └────────┘     └────────┘     │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Trading Cycle

Each broker operates on a 2.5-minute trading cycle:

1. **Check Balance** - Verify broker is still funded
2. **Run Trading Logic** - Execute APEX v7.1 strategy
3. **Handle Errors** - Catch and log any failures
4. **Wait 2.5 Minutes** - Sleep until next cycle
5. **Repeat** - Continue indefinitely

If a broker encounters an error:
- Error is logged with broker name
- Health status is updated
- Other brokers are unaffected
- Failed broker retries on next cycle

## Configuration

### Enable Independent Trading

Set in `.env` file:
```bash
MULTI_BROKER_INDEPENDENT=true
```

### Minimum Balance Requirement

Default: **$10.00 USD**

This is defined in `bot/independent_broker_trader.py`:
```python
MINIMUM_FUNDED_BALANCE = 10.0
```

Brokers with balances below this threshold are skipped.

## Checking Status

### Method 1: Run Status Script

```bash
python3 check_independent_broker_status.py
```

This shows:
- Which brokers are connected
- Which brokers are funded
- Independent trading status
- Configuration settings

### Method 2: Check Broker Status

```bash
python3 check_broker_status.py
```

Shows connection status and balances for all brokers.

### Method 3: Check Active Trading

```bash
python3 check_active_trading_per_broker.py
```

Shows which brokers are actively trading with open positions.

## Example Scenario

### Scenario: Coinbase API Goes Down

**Without Independent Trading:**
```
❌ Coinbase fails
❌ Entire bot stops
❌ No trading on any broker
❌ Manual intervention required
```

**With Independent Trading:**
```
❌ Coinbase thread encounters error
✅ Error logged: "Coinbase: Connection timeout"
✅ Coinbase health status: "degraded"
✅ Kraken continues trading normally
✅ OKX continues trading normally
✅ Binance continues trading normally
✅ Coinbase automatically retries next cycle
✅ When Coinbase recovers, trading resumes
```

## Health Monitoring

Each broker tracks:
- **Status**: `healthy`, `degraded`, or `failed`
- **Error Count**: Number of consecutive errors
- **Total Cycles**: Total trading cycles attempted
- **Successful Cycles**: Successfully completed cycles
- **Success Rate**: Percentage of successful cycles
- **Last Error**: Most recent error message

### Viewing Health Status

The bot logs status summaries every 25 minutes:

```
==================================================================================
📊 MULTI-BROKER TRADING STATUS SUMMARY
==================================================================================
Total Brokers: 5
Connected: 3
Funded: 3
Active Trading Threads: 3

coinbase:
   Status: healthy
   Trading: ✅ Yes
   Cycles: 48/50 successful
   Success Rate: 96.0%

kraken:
   Status: degraded
   Trading: ✅ Yes
   Cycles: 45/50 successful
   Success Rate: 90.0%
   ⚠️  Recent Errors: 3

okx:
   Status: healthy
   Trading: ✅ Yes
   Cycles: 50/50 successful
   Success Rate: 100.0%
==================================================================================
```

## Logs

Each broker's actions are prefixed with the broker name:

```
2026-01-08 16:30:00 | INFO | 🔄 coinbase - Cycle #42
2026-01-08 16:30:01 | INFO |    coinbase: Running trading cycle...
2026-01-08 16:30:05 | INFO |    ✅ coinbase cycle completed successfully
2026-01-08 16:30:05 | INFO |    coinbase: Waiting 2.5 minutes until next cycle...

2026-01-08 16:30:00 | INFO | 🔄 kraken - Cycle #42
2026-01-08 16:30:01 | INFO |    kraken: Running trading cycle...
2026-01-08 16:30:03 | ERROR | ❌ kraken trading cycle failed: Connection timeout
2026-01-08 16:30:03 | INFO |    ⚠️  kraken will retry next cycle
```

## Answers to User Questions

### 1. Does NIJA see all brokerage accounts?

**✅ YES**

NIJA attempts to connect to all configured brokers:
- Coinbase Advanced Trade
- Kraken Pro
- OKX
- Binance
- Alpaca

Run `check_broker_status.py` to see which brokers are visible and connected.

### 2. Does NIJA see which brokerages are funded?

**✅ YES**

NIJA automatically detects funded brokers:
- Checks balance on each connected broker
- Identifies brokers with balance ≥ $10
- Only starts trading threads for funded brokers

Run `check_independent_broker_status.py` to see which brokers are funded.

### 3. Is NIJA trading each brokerage independently?

**✅ YES (when enabled)**

With `MULTI_BROKER_INDEPENDENT=true`:
- Each funded broker runs in its own thread
- Full error isolation between brokers
- Failures don't cascade
- Independent health monitoring
- Automatic recovery

**How to verify:**
1. Check environment variable: `echo $MULTI_BROKER_INDEPENDENT`
2. Run status check: `python3 check_independent_broker_status.py`
3. Watch logs for independent thread messages

## Troubleshooting

### No Funded Brokers Detected

**Problem:** Script shows no funded brokers

**Solutions:**
1. Check broker credentials are configured in `.env`
2. Verify API keys have correct permissions
3. Ensure account balances are ≥ $10
4. Run `check_broker_status.py` to debug connections

### Independent Trading Not Starting

**Problem:** Bot uses single-broker mode instead

**Solutions:**
1. Check `MULTI_BROKER_INDEPENDENT` is set to `true`
2. Verify at least one broker is funded
3. Check logs for initialization errors
4. Ensure `independent_broker_trader.py` is present

### One Broker Keeps Failing

**Problem:** Specific broker shows continuous errors

**What to Check:**
1. API credentials for that broker
2. API permissions (trading, account access)
3. Broker's API status (maintenance, outages)
4. Network connectivity to that exchange
5. Balance still meets minimum requirement

**Expected Behavior:**
- Failing broker logs errors
- Other brokers continue normally
- Failing broker retries automatically
- If persistent, check credentials/API status

### All Brokers Stopped

**Problem:** No trading activity on any broker

**Solutions:**
1. Check bot is running: `ps aux | grep python`
2. Review logs for fatal errors: `tail -100 nija.log`
3. Verify credentials for all brokers
4. Check EMERGENCY_STOP file doesn't exist
5. Restart bot: `./start.sh`

## Migration from Single-Broker Mode

### Before (Single-Broker Mode)
```python
# One broker, one thread
# If Coinbase fails, everything stops
strategy.run_cycle()  # Only trades Coinbase
```

### After (Independent Multi-Broker Mode)
```python
# Multiple brokers, isolated threads
# Each broker trades independently
strategy.start_independent_multi_broker_trading()
# Coinbase, Kraken, OKX all trade simultaneously
# Failures are isolated
```

### Steps to Migrate

1. **Update Configuration**
   ```bash
   echo "MULTI_BROKER_INDEPENDENT=true" >> .env
   ```

2. **Configure Additional Brokers** (optional)
   Add credentials in `.env` for other brokers you want to use

3. **Restart Bot**
   ```bash
   ./start.sh
   ```

4. **Verify Status**
   ```bash
   python3 check_independent_broker_status.py
   ```

## Performance Considerations

### Resource Usage

**Single-Broker Mode:**
- 1 thread
- Minimal overhead

**Independent Multi-Broker Mode:**
- 1 thread per funded broker
- Each thread runs independently
- Slightly higher memory usage
- No performance impact on trading logic

### Recommended Setup

For production with multiple brokers:
- Use servers with at least 1GB RAM
- Monitor logs for memory issues
- Start with 2-3 brokers initially
- Scale up as needed

## Best Practices

1. **Start Small**
   - Enable independent trading on 1-2 brokers first
   - Verify it works as expected
   - Add more brokers gradually

2. **Monitor Health**
   - Check status script regularly
   - Watch for brokers with low success rates
   - Investigate persistent errors

3. **Balance Distribution**
   - Distribute capital across brokers
   - Don't put all funds in one broker
   - Consider exchange-specific risks

4. **API Limits**
   - Each broker has its own rate limits
   - Independent threads respect per-broker limits
   - No cross-broker rate limit conflicts

5. **Logging**
   - Keep logs for at least 7 days
   - Monitor for patterns in failures
   - Use logs to optimize broker selection

## Support

For issues or questions:
1. Check logs: `tail -f nija.log`
2. Run status scripts
3. Review this documentation
4. Check BROKER_INTEGRATION_GUIDE.md for broker-specific setup

## Related Documentation

- `BROKER_INTEGRATION_GUIDE.md` - Broker setup instructions
- `check_broker_status.py` - Connection status checker
- `check_active_trading_per_broker.py` - Trading activity checker
- `check_independent_broker_status.py` - Independent trading status
- `.env.example` - Configuration examples
