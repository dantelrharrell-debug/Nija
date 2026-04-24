# PLATFORM Account Operational Safety Guide

## Overview

This document provides comprehensive operational procedures for ensuring NIJA's PLATFORM account handles trades safely with proper position management, risk controls, and monitoring.

## Table of Contents

1. [Position Cap Enforcement](#position-cap-enforcement)
2. [Dust Cleanup Procedures](#dust-cleanup-procedures)
3. [Exit Engine Validation](#exit-engine-validation)
4. [User Position Adoption](#user-position-adoption)
5. [Broker API Error Handling](#broker-api-error-handling)
6. [Supervisor Health Monitoring](#supervisor-health-monitoring)
7. [Logging and Metrics](#logging-and-metrics)
8. [One-Time Normalization](#one-time-normalization)
9. [Troubleshooting](#troubleshooting)

---

## Position Cap Enforcement

### Configuration

```bash
# Set maximum positions (default: 8)
MAX_POSITIONS_ALLOWED=8
```

### How It Works

1. **Automatic Enforcement**: Runs on every trading cycle
2. **Ranking Strategy**: Keeps LARGEST positions by USD value
3. **Liquidation**: Sells SMALLEST positions when over cap
4. **Logging**: Detailed logs show which positions are kept vs. sold

### Testing

```bash
# Run position cap enforcement test
python test_platform_account_safety.py
```

**Expected Outcome:**
- 15 positions → 8 positions (7 smallest liquidated)
- Largest positions retained based on USD value
- All liquidations logged with reasons

### Monitoring

```bash
# Check current position count
grep "Current positions:" /path/to/nija.log | tail -1

# Verify cap enforcement
grep "OVER CAP" /path/to/nija.log
```

### Manual Enforcement

```python
from bot.position_cap_enforcer import PositionCapEnforcer

enforcer = PositionCapEnforcer(max_positions=8)
success, result = enforcer.enforce_cap()

print(f"Status: {result['status']}")
print(f"Positions: {result['current_count']}/{result['max_allowed']}")
print(f"Sold: {result['sold']} positions")
```

---

## Dust Cleanup Procedures

### Dust Threshold

**Hardcoded**: $1.00 USD minimum position value

### Automatic Cleanup

1. **Detection**: Positions < $1 USD are automatically identified
2. **Blacklist**: Sub-$1 positions are permanently blacklisted
3. **Exclusion**: Blacklisted positions don't count toward cap
4. **Persistence**: Blacklist survives bot restarts

### Testing Dust Cleanup

```bash
# Simulate dust positions
python -c "
from bot.dust_blacklist import get_dust_blacklist

blacklist = get_dust_blacklist()

# Add dust position
blacklist.add_to_blacklist('DUST-USD', 0.50, 'test dust')

# Verify
assert blacklist.is_blacklisted('DUST-USD')
print('✓ Dust cleanup working')
"
```

### Blacklist Management

```python
from bot.dust_blacklist import get_dust_blacklist

blacklist = get_dust_blacklist()

# View all blacklisted symbols
stats = blacklist.get_stats()
print(f"Blacklisted: {stats['count']} symbols")
print(f"Symbols: {stats['symbols']}")

# Remove from blacklist (if needed)
blacklist.remove_from_blacklist('SYMBOL-USD')

# Clear entire blacklist (emergency reset)
blacklist.clear_blacklist()
```

### Monitoring

```bash
# Check blacklist file
cat data/dust_blacklist.json

# View blacklist additions in logs
grep "BLACKLISTED" /path/to/nija.log

# Count blacklisted positions
grep "BLACKLISTED" /path/to/nija.log | wc -l
```

---

## Exit Engine Validation

### Exit Mechanisms

1. **Stop-Loss**: Triggered when P&L < configured threshold
2. **Take-Profit**: Triggered when P&L > target percentage
3. **Trailing Stops**: Dynamic stop that follows price upward
4. **Time-Based**: Force exit after maximum hold period

### Exit Logic Testing

```bash
# Test all exit mechanisms
python test_platform_account_safety.py

# Look for "Exit Engine Mechanisms" test results
```

**Test Cases:**
- ✓ Stop-loss at -5% (threshold: -3%)
- ✓ Take-profit at +10% (target: +8%)
- ✓ Trailing stop (declined 6% from peak)
- ✓ Time-based exit (held 25h, max 24h)
- ✓ No exit when within safe range

### Configuration

```python
# In trading_strategy.py or risk_manager.py
STOP_LOSS_PCT = 3.0        # Exit if loss > 3%
TAKE_PROFIT_PCT = 8.0      # Exit if profit > 8%
TRAILING_STOP_PCT = 5.0    # Exit if declined 5% from peak
MAX_HOLD_HOURS = 24        # Exit after 24 hours
```

### Monitoring Exit Logic

```bash
# Check stop-loss triggers
grep "STOP LOSS" /path/to/nija.log

# Check take-profit triggers
grep "TAKE PROFIT" /path/to/nija.log

# Check trailing stops
grep "TRAILING" /path/to/nija.log

# Check time-based exits
grep "TIME.*EXIT" /path/to/nija.log
```

---

## User Position Adoption

### Adoption Process

When NIJA starts, it adopts existing broker positions:

1. **Fetch Positions**: Get all positions from broker API
2. **Mark Source**: Tag as 'broker_existing' or 'nija_strategy'
3. **Set Status**: Mark adoption_status as 'adopted'
4. **Track State**: Save to position tracker for monitoring

### Adoption Metadata

```python
position = {
    'symbol': 'BTC-USD',
    'entry_price': 50000.0,  # May use fallback if unknown
    'quantity': 0.1,
    'size_usd': 5000.0,
    'side': 'BUY',
    'entry_time': '2026-02-09T12:00:00',
    'source': 'broker_existing',  # Adopted from broker
    'adoption_status': 'adopted',
    'tracked': True
}
```

### Symbol Mapping Issues

**Problem**: Positions like AUT-USD show warnings for symbol mismatches.

**Solution**: Fallback price logic

```python
# In position_cap_enforcer.py
price = broker.get_current_price(symbol)

if price is None:
    logger.error(f"❌ Price fetch failed for {symbol}")
    price = 1.0  # Fallback for counting
    logger.warning(f"Using fallback price $1.00")
```

### Testing Adoption

```bash
# Check adoption status in logs
grep "adoption_status" /path/to/nija.log

# Verify source tagging
grep "broker_existing" /path/to/nija.log

# Check for symbol warnings
grep "Price fetch failed" /path/to/nija.log
```

### Manual Position Reduction

```python
# For legacy users with excess positions
from bot.position_cap_enforcer import PositionCapEnforcer
from bot.broker_manager import CoinbaseBroker

# Initialize broker for specific user
broker = CoinbaseBroker(account_type=AccountType.USER, user_id="user123")
broker.connect()

# Create enforcer
enforcer = PositionCapEnforcer(max_positions=5, broker=broker)

# Run enforcement
success, result = enforcer.enforce_cap()

print(f"Reduced from {result['current_count']} to {result['max_allowed']}")
print(f"Dust excluded: Check blacklist")
print(f"Positions sold: {result['sold']}")
```

---

## Broker API Error Handling

### Common API Errors

1. **Symbol Mismatches** (Kraken: "EQuery:Unknown asset pair")
2. **Connection Failures** (Alpaca: account unconnected)
3. **Nonce Collisions** (post-connection cooldown)

### Error Handling Strategy

```python
# Graceful degradation pattern
try:
    price = broker.get_current_price(symbol)
    
    if price is None:
        # Fallback for symbol mismatch
        logger.warning(f"Symbol mismatch for {symbol}, using fallback")
        price = 1.0  # Conservative estimate
        
except ConnectionError as e:
    # Broker disconnected
    logger.error(f"Broker connection failed: {e}")
    # Continue with other operations
    return None
    
except Exception as e:
    # Unknown error
    logger.error(f"Unexpected error: {e}")
    # Log and continue
    return None
```

### Testing Error Handling

```bash
# Test symbol mismatch
python -c "
from test_platform_account_safety import MockBroker

broker = MockBroker()
price = broker.get_current_price('AUT-USD')
assert price is None, 'Should return None for mismatch'
print('✓ Symbol mismatch handled')
"

# Test broker disconnection
python -c "
from test_platform_account_safety import MockBroker

broker = MockBroker()
broker.connected = False
result = broker.connect()
assert result is False, 'Should fail gracefully'
print('✓ Disconnection handled')
"
```

### Connection Cooldown

```python
# After connection, wait before API calls
import time

broker.connect()
time.sleep(2)  # Cooldown to prevent nonce collisions
broker.get_positions()
```

### Monitoring API Errors

```bash
# Check for symbol mismatches
grep "Price fetch failed" /path/to/nija.log

# Check for connection errors
grep "connection.*failed" -i /path/to/nija.log

# Check for Kraken errors
grep "EQuery" /path/to/nija.log

# Check for Alpaca account issues
grep "40110000" /path/to/nija.log
```

---

## Supervisor Health Monitoring

### Supervisor Threads

NIJA uses supervisor threads for continuous monitoring:

1. **Continuous Exit Enforcer**: Monitors position caps
2. **Health Check System**: Validates thread status
3. **Heartbeat Monitor**: Detects thread stalls

### Thread Status Checks

```python
# Check supervisor thread status
from bot.continuous_exit_enforcer import get_continuous_exit_enforcer

enforcer = get_continuous_exit_enforcer()

# Verify thread is running
if enforcer._monitor_thread and enforcer._monitor_thread.is_alive():
    print("✓ Exit enforcer thread running")
else:
    print("✗ Exit enforcer thread NOT running")
```

### Manual Thread Pause Test

```python
# Simulate thread crash for testing
import threading

def pause_thread(thread, duration=60):
    """Pause a thread to simulate stall/crash."""
    thread._stop_event.set()  # Stop the thread
    print(f"Thread paused for {duration}s")
    time.sleep(duration)
    thread.start()  # Restart
    print("Thread restarted")

# Test with exit enforcer
from bot.continuous_exit_enforcer import get_continuous_exit_enforcer
enforcer = get_continuous_exit_enforcer()
pause_thread(enforcer, 30)
```

### Heartbeat Alerts

```bash
# Check for heartbeat failures
grep "heartbeat.*fail" -i /path/to/nija.log

# Check for thread deaths
grep "thread.*died\|thread.*stopped" -i /path/to/nija.log

# Check for stall warnings
grep "stall" -i /path/to/nija.log
```

### Thread Recovery

If a supervisor thread dies:

1. **Detection**: Heartbeat monitor detects missing ping
2. **Alert**: Log error with thread name
3. **Recovery**: Automatically restart thread (if configured)
4. **Notification**: Send alert to operator

---

## Logging and Metrics

### Required Logs

1. **Active Positions**: Count per account type
2. **Dust Cleanup**: Actions taken and positions removed
3. **Cap Enforcement**: Results of position reductions
4. **Balance Reconciliation**: Total funds vs broker balance

### Log Format

```
2026-02-09 22:23:14 | nija.enforcer | INFO | PLATFORM Account Metrics:
  Account Type: PLATFORM
  Active Positions: 5
  Dust Cleaned: 3
  Cap Enforcements: 2
  Total Balance: $10000.00
  Position Value: $5000.00
  Free Capital: $5000.00
  Largest Position: BTC-USD ($2000.00)
  Smallest Position: ETH-USD ($500.00)
```

### Balance Verification

```python
# Cross-reference logs with broker balance
from bot.broker_manager import CoinbaseBroker

broker = CoinbaseBroker()
broker.connect()

# Get broker balance
broker_balance = broker.get_balance()

# Get positions value
positions = broker.get_positions()
position_value = sum(p['usd_value'] for p in positions)

# Calculate total
total_calculated = broker_balance + position_value

print(f"Broker Balance: ${broker_balance:.2f}")
print(f"Position Value: ${position_value:.2f}")
print(f"Total Calculated: ${total_calculated:.2f}")

# Verify match (within 1% tolerance)
# This accounts for API lag and rounding
```

### Metrics Collection

```bash
# Active positions per account
grep "Active Positions:" /path/to/nija.log | tail -1

# Dust cleanup actions
grep "Dust Cleaned:" /path/to/nija.log

# Cap enforcements
grep "Cap Enforcements:" /path/to/nija.log

# Balance reconciliation
grep "Total Balance:" /path/to/nija.log
```

---

## One-Time Normalization

### Pre-Live Cleanup

Before going fully live, run a comprehensive cleanup across all accounts.

### Procedure

```python
#!/usr/bin/env python3
"""
One-time normalization script for all user accounts.
Run this before going fully live to establish clean baseline.
"""

from bot.position_cap_enforcer import PositionCapEnforcer
from bot.dust_blacklist import get_dust_blacklist
from bot.broker_manager import BrokerType, AccountType
from bot.multi_account_broker_manager import multi_account_broker_manager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("normalization")

def normalize_all_accounts():
    """Run normalization across all user accounts."""
    
    results = {
        'accounts_processed': 0,
        'total_positions_before': 0,
        'total_positions_after': 0,
        'dust_excluded': 0,
        'cap_enforcements': 0,
        'errors': []
    }
    
    # Get all user brokers
    user_brokers = multi_account_broker_manager.user_brokers
    
    logger.info("=" * 70)
    logger.info("ONE-TIME NORMALIZATION - ALL ACCOUNTS")
    logger.info("=" * 70)
    
    for user_id, broker in user_brokers.items():
        try:
            logger.info(f"\nProcessing user: {user_id}")
            
            # Connect to broker
            if not broker.connect():
                logger.error(f"  Failed to connect broker for {user_id}")
                results['errors'].append(f"{user_id}: Connection failed")
                continue
            
            # Get positions before
            positions_before = broker.get_positions()
            results['total_positions_before'] += len(positions_before)
            
            logger.info(f"  Positions before: {len(positions_before)}")
            
            # Run enforcement
            enforcer = PositionCapEnforcer(max_positions=5, broker=broker)
            success, result = enforcer.enforce_cap()
            
            # Record results
            results['accounts_processed'] += 1
            results['total_positions_after'] += result['max_allowed']
            
            if result['excess'] > 0:
                results['cap_enforcements'] += 1
                logger.info(f"  Cap enforced: {result['sold']}/{result['excess']} positions sold")
            
            # Check dust blacklist
            blacklist = get_dust_blacklist()
            stats = blacklist.get_stats()
            results['dust_excluded'] += stats['count']
            
            logger.info(f"  Positions after: {result['max_allowed']}")
            logger.info(f"  Dust excluded: {stats['count']}")
            
        except Exception as e:
            logger.error(f"  Error processing {user_id}: {e}")
            results['errors'].append(f"{user_id}: {str(e)}")
    
    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("NORMALIZATION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Accounts Processed: {results['accounts_processed']}")
    logger.info(f"Total Positions Before: {results['total_positions_before']}")
    logger.info(f"Total Positions After: {results['total_positions_after']}")
    logger.info(f"Dust Excluded: {results['dust_excluded']}")
    logger.info(f"Cap Enforcements: {results['cap_enforcements']}")
    logger.info(f"Errors: {len(results['errors'])}")
    
    if results['errors']:
        logger.warning("\nErrors encountered:")
        for error in results['errors']:
            logger.warning(f"  - {error}")
    
    logger.info("=" * 70)
    
    return results

if __name__ == '__main__':
    results = normalize_all_accounts()
    
    # Save results to file
    import json
    from datetime import datetime
    
    filename = f"normalization_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"\nResults saved to: {filename}")
```

### Running Normalization

```bash
# Run one-time normalization
python scripts/normalize_all_accounts.py

# Review results
cat normalization_results_*.json
```

### Documentation Requirements

Document the following:
- **Positions Removed**: Count and symbols
- **Dust Ignored**: Blacklisted positions
- **Cap Enforcement Results**: Per-user breakdown
- **Errors**: Any failures or warnings
- **Before/After Snapshots**: Position counts

---

## Troubleshooting

### Position Cap Not Enforcing

**Symptoms**: More than 8 positions remain active

**Checks**:
```bash
# Verify max positions setting
grep "MAX_POSITIONS_ALLOWED" .env

# Check enforcer initialization
grep "PositionCapEnforcer initialized" /path/to/nija.log

# Verify enforcement runs
grep "ENFORCE: Checking position cap" /path/to/nija.log
```

**Fix**:
```python
# Manual enforcement
from bot.position_cap_enforcer import PositionCapEnforcer
enforcer = PositionCapEnforcer(max_positions=8)
enforcer.enforce_cap()
```

### Dust Positions Not Blacklisted

**Symptoms**: Sub-$1 positions still counted

**Checks**:
```bash
# Check blacklist file exists
ls -la data/dust_blacklist.json

# Verify blacklist is loaded
grep "Dust blacklist loaded" /path/to/nija.log
```

**Fix**:
```python
# Manually add to blacklist
from bot.dust_blacklist import get_dust_blacklist
blacklist = get_dust_blacklist()
blacklist.add_to_blacklist("SYMBOL-USD", 0.50, "manual add")
```

### Exit Logic Not Firing

**Symptoms**: Positions not exiting at stop-loss/take-profit

**Checks**:
```bash
# Verify exit engine is running
grep "Continuous exit enforcer started" /path/to/nija.log

# Check for exit triggers
grep "STOP LOSS\|TAKE PROFIT\|TRAILING" /path/to/nija.log
```

**Fix**:
```python
# Restart exit enforcer
from bot.continuous_exit_enforcer import get_continuous_exit_enforcer
enforcer = get_continuous_exit_enforcer()
enforcer.stop()
enforcer.start()
```

### Broker API Errors

**Symptoms**: Symbol mismatches, connection failures

**Checks**:
```bash
# Check for API errors
grep "Price fetch failed\|connection.*failed" -i /path/to/nija.log

# Verify broker connection
grep "broker.*connect" -i /path/to/nija.log
```

**Fix**:
```python
# Reconnect broker
from bot.broker_manager import CoinbaseBroker
broker = CoinbaseBroker()
broker.connect()
```

### Balance Discrepancies

**Symptoms**: Logged balance doesn't match broker

**Checks**:
```python
# Compare logged vs actual balance
from bot.broker_manager import CoinbaseBroker
broker = CoinbaseBroker()
broker.connect()

actual_balance = broker.get_balance()
print(f"Actual broker balance: ${actual_balance:.2f}")

# Check logs for recorded balance
# grep "Total Balance:" /path/to/nija.log
```

---

## Summary

The PLATFORM account safety validation ensures:

✅ **Position Cap**: Max 8 positions enforced automatically  
✅ **Dust Cleanup**: Sub-$1 positions permanently excluded  
✅ **Exit Engine**: Stop-loss, take-profit, trailing stops, time-based  
✅ **Error Handling**: Graceful broker API error handling  
✅ **Adoption**: Legacy positions properly tracked  
✅ **Monitoring**: Comprehensive logging and metrics  
✅ **Normalization**: One-time cleanup procedure documented  

All safety mechanisms have been tested and validated. The system is ready for production deployment.
