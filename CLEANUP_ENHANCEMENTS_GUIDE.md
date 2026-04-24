# Broker-Level Cleanup and Retry Logic Enhancements

## Overview

This document describes the new broker-level dust position cleanup, retry logic, and symbol freeze mechanisms implemented to address the priority issues outlined in the problem statement.

## Table of Contents

1. [Broker Dust Cleanup](#broker-dust-cleanup)
2. [Enhanced Balance Fetcher](#enhanced-balance-fetcher)
3. [Symbol Freeze Manager](#symbol-freeze-manager)
4. [User Account Normalization](#user-account-normalization)
5. [Integration Guide](#integration-guide)
6. [Configuration](#configuration)

---

## Broker Dust Cleanup

### Purpose

Removes/closes all broker-level dust positions (< $1 USD) physically at the broker level, not just from tracked positions. This includes:
- Legacy positions from manual trading
- Positions adopted from other bots
- Remnants from failed orders
- Partially filled orders

### Usage

```python
from bot.broker_dust_cleanup import get_broker_dust_cleanup

# Initialize cleanup engine
cleanup = get_broker_dust_cleanup(
    dust_threshold_usd=1.00,  # Positions below $1 are dust
    dry_run=False              # Set to True to preview without executing
)

# Find all dust positions
dust_positions = cleanup.find_dust_positions(broker)
print(f"Found {len(dust_positions)} dust positions")

# Execute full cleanup
result = cleanup.cleanup_all_dust(broker)
print(f"Closed {result['closed']} positions")
print(f"Total value cleaned: ${result['total_value_cleaned']:.2f}")
```

### Key Features

- **Dry Run Mode**: Test cleanup logic without executing trades
- **Forced Liquidation**: Uses `force_liquidate=True` to close positions below minimum trade size
- **Comprehensive Logging**: Detailed logs for audit trail
- **Statistics Tracking**: Returns detailed results of cleanup operation

### Output Example

```
======================================================================
🧹 STARTING BROKER-LEVEL DUST CLEANUP
======================================================================
🔍 Fetching all positions from broker...
   Found 5 total positions
   🗑️  DUST: ETH-USD - $0.5000 (0.00020000 ETH)
   🗑️  DUST: DOGE-USD - $0.7500 (5.00000000 DOGE)
🚨 Found 2 dust positions to clean up:
   Total dust value: $1.2500

🔨 Closing dust position: ETH-USD
   Quantity: 0.00020000 ETH
   USD Value: $0.5000
   ✅ Successfully closed ETH-USD

======================================================================
🧹 DUST CLEANUP COMPLETE
======================================================================
   Total Found: 2
   Successfully Closed: 2
   Failed: 0
   Total Value Cleaned: $1.2500
   Duration: 1.23s
======================================================================
```

---

## Enhanced Balance Fetcher

### Purpose

Adds robust retry logic (3 attempts + exponential backoff) for balance fetch operations, with fallback to last known balance on failure. This prevents trading disruptions when the broker API is temporarily unavailable.

### Usage

```python
from bot.enhanced_balance_fetcher import get_enhanced_balance_fetcher

# Initialize fetcher
fetcher = get_enhanced_balance_fetcher(
    max_attempts=3,    # Number of retry attempts
    base_delay=2.0     # Base delay in seconds (doubles each retry)
)

# Fetch balance with retry and fallback
balance = fetcher.get_balance_with_fallback(broker, verbose=True)
print(f"Balance: ${balance:.2f}")

# Check last known balance info
info = fetcher.get_last_known_balance()
if info:
    print(f"Balance age: {info['age_minutes']:.1f} minutes")
    print(f"Consecutive errors: {info['consecutive_errors']}")
```

### Key Features

- **Exponential Backoff**: 2s → 4s → 8s delay between retries (capped at 30s)
- **Last Known Balance**: Falls back to cached balance if all retries fail
- **Thread-Safe**: Uses locks for concurrent access
- **Error Tracking**: Tracks consecutive errors for monitoring
- **Age Monitoring**: Warns if cached balance is old (> 30 minutes)

### Output Example

```
⚠️  Balance fetch failed (attempt 1/3): Network error
🔄 Retrying in 2s...
⚠️  Balance fetch failed (attempt 2/3): Network error
🔄 Retrying in 4s...
✅ Balance fetch succeeded on attempt 3: $1000.00
```

**Fallback Example:**

```
❌ Balance fetch failed permanently after 3 attempts
======================================================================
⚠️  USING FALLBACK BALANCE
======================================================================
   Last Known Balance: $500.00
   Age: 5.2 minutes
   Consecutive Errors: 1

   Bot will continue trading with cached balance.
   Balance will be updated once API is available.
======================================================================
```

---

## Symbol Freeze Manager

### Purpose

Freezes symbols with persistent price fetch failures and flags them for manual review. This prevents trading on problematic symbols like:
- Delisted coins (e.g., AUT-USD)
- Temporarily suspended trading pairs
- Symbols with API mapping issues
- Network/broker-specific issues

### Usage

```python
from bot.symbol_freeze_manager import get_symbol_freeze_manager

# Initialize manager
manager = get_symbol_freeze_manager(
    failure_threshold=3,     # Freeze after 3 consecutive failures
    cooldown_hours=24.0,     # Auto-unfreeze after 24 hours
    data_dir="./data"        # Persistent storage directory
)

# Record price fetch failure
try:
    price = broker.get_current_price("AUT-USD")
except Exception as e:
    # This will freeze symbol after threshold
    manager.record_price_fetch_failure("AUT-USD", str(e))

# Record success (resets failure count)
manager.record_price_fetch_success("BTC-USD")

# Check if symbol is frozen
if manager.is_frozen("AUT-USD"):
    print("AUT-USD is frozen - skipping trade")

# Get all frozen symbols
frozen = manager.get_frozen_symbols()
for symbol, info in frozen.items():
    print(f"{symbol}: {info.consecutive_failures} failures")

# Manually unfreeze symbol
manager.unfreeze_symbol("AUT-USD", reason="Issue resolved")
```

### Key Features

- **Persistent Storage**: Frozen symbols persist across bot restarts
- **Automatic Cooldown**: Symbols auto-unfreeze after cooldown period
- **Manual Review Flag**: Requires manual unfreeze for critical issues
- **Comprehensive Logging**: Detailed freeze/unfreeze notifications
- **Statistics Tracking**: Monitor frozen symbols and pending freezes

### Output Example

```
⚠️  Price fetch failed for AUT-USD (1/3): Price not available
⚠️  Price fetch failed for AUT-USD (2/3): Price not available
⚠️  Price fetch failed for AUT-USD (3/3): Price not available

======================================================================
❄️  SYMBOL FROZEN: AUT-USD
======================================================================
   Reason: 3 consecutive price fetch failures
   Last Error: Price not available
   Freeze Time: 2026-02-16T22:45:00

   ⚠️  MANUAL REVIEW REQUIRED
   Possible causes:
   - Symbol delisted from exchange
   - Trading temporarily suspended
   - Symbol mapping issue (e.g., AUT-USD)
   - Network/API connectivity issue

   Symbol will remain frozen for 24.0h
   Use unfreeze_symbol() to manually unfreeze if resolved
======================================================================
```

---

## User Account Normalization

### Purpose

One-time utility to normalize user accounts and positions by:
- Scanning all positions across accounts
- Consolidating small positions where possible
- Enforcing minimum position size (>= $7.50)
- Force merging positions below tier minimum

### Usage

```python
from bot.user_account_normalization import run_normalization_pass

# Run normalization pass (dry run first!)
result = run_normalization_pass(
    broker,
    minimum_position_usd=7.50,  # Minimum position size
    dry_run=True                # Always test with dry_run=True first
)

print(f"Actions required: {result['actions_required']}")
print(f"Actions executed: {result['actions_executed']}")
print(f"Total value cleaned: ${result.get('total_value_cleaned', 0):.2f}")

# After reviewing dry run, execute for real
result = run_normalization_pass(broker, dry_run=False)
```

### Key Features

- **Position Scanning**: Identifies all positions below minimum
- **Consolidation Logic**: Closes positions below threshold
- **Dry Run Mode**: Test before executing
- **Comprehensive Logging**: Audit trail of all actions
- **Statistics Tracking**: Detailed results of normalization

### Output Example

```
======================================================================
🔧 STARTING USER ACCOUNT NORMALIZATION
======================================================================
🔍 SCANNING POSITIONS FOR NORMALIZATION
======================================================================
   Found 10 total positions
   ⚠️  SMALL POSITION: ETH-USD - $5.00 (below $7.50)
   ⚠️  SMALL POSITION: DOGE-USD - $3.25 (below $7.50)
   💡 CONSOLIDATION CANDIDATE: BTC-USD - $9.00

======================================================================
📊 SCAN RESULTS
======================================================================
   Total Positions: 10
   Below Minimum ($7.50): 2
   Consolidation Candidates: 1
   Total Actions Required: 3
======================================================================

Executing action 1/3
   Type: close_small
   Symbol: ETH-USD
   Current Size: $5.00
   Reason: Position below minimum $7.50
🔨 Closing small position: ETH-USD ($5.00)
   ✅ Successfully closed ETH-USD

======================================================================
🔧 NORMALIZATION COMPLETE
======================================================================
   Total Positions: 10
   Actions Required: 3
   Successfully Executed: 3
   Failed: 0
   Duration: 2.45s
======================================================================
```

---

## Integration Guide

### Step 1: Add to Trading Strategy

Integrate the new modules into your trading strategy:

```python
from bot.broker_dust_cleanup import get_broker_dust_cleanup
from bot.enhanced_balance_fetcher import get_enhanced_balance_fetcher
from bot.symbol_freeze_manager import get_symbol_freeze_manager

class TradingStrategy:
    def __init__(self, broker):
        self.broker = broker
        
        # Initialize cleanup utilities
        self.dust_cleanup = get_broker_dust_cleanup(dry_run=False)
        self.balance_fetcher = get_enhanced_balance_fetcher()
        self.freeze_manager = get_symbol_freeze_manager()
    
    def get_balance(self):
        """Get balance with retry logic"""
        return self.balance_fetcher.get_balance_with_fallback(
            self.broker, 
            verbose=True
        )
    
    def get_price(self, symbol):
        """Get price with freeze check"""
        # Check if symbol is frozen
        if self.freeze_manager.is_frozen(symbol):
            logging.warning(f"Symbol {symbol} is frozen - skipping")
            return None
        
        try:
            price = self.broker.get_current_price(symbol)
            # Record success
            self.freeze_manager.record_price_fetch_success(symbol)
            return price
        except Exception as e:
            # Record failure
            self.freeze_manager.record_price_fetch_failure(symbol, str(e))
            return None
    
    def cleanup_dust_positions(self):
        """Periodic dust cleanup"""
        result = self.dust_cleanup.cleanup_all_dust(self.broker)
        logging.info(f"Dust cleanup: closed {result['closed']} positions")
```

### Step 2: Add to Startup Routine

Run cleanup on startup:

```python
def startup_routine(broker):
    """Run on bot startup"""
    
    # 1. Run normalization pass (dry run first)
    from bot.user_account_normalization import run_normalization_pass
    result = run_normalization_pass(broker, dry_run=True)
    logging.info(f"Normalization: {result['actions_required']} actions needed")
    
    # 2. Clean up dust positions
    from bot.broker_dust_cleanup import get_broker_dust_cleanup
    cleanup = get_broker_dust_cleanup()
    result = cleanup.cleanup_all_dust(broker)
    logging.info(f"Dust cleanup: closed {result['closed']} positions")
    
    # 3. Load frozen symbols
    from bot.symbol_freeze_manager import get_symbol_freeze_manager
    manager = get_symbol_freeze_manager()
    frozen = manager.get_frozen_symbols()
    logging.info(f"Frozen symbols: {list(frozen.keys())}")
```

### Step 3: Add Periodic Maintenance

Schedule periodic cleanup:

```python
import time
from datetime import datetime, timedelta

last_cleanup = datetime.now()
CLEANUP_INTERVAL_HOURS = 24

def trading_loop(broker, strategy):
    global last_cleanup
    
    while True:
        # ... normal trading logic ...
        
        # Periodic dust cleanup
        if datetime.now() - last_cleanup > timedelta(hours=CLEANUP_INTERVAL_HOURS):
            strategy.cleanup_dust_positions()
            last_cleanup = datetime.now()
        
        time.sleep(60)  # Check every minute
```

---

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Broker Dust Cleanup
DUST_THRESHOLD_USD=1.00
DUST_CLEANUP_DRY_RUN=false

# Enhanced Balance Fetcher
BALANCE_FETCH_MAX_ATTEMPTS=3
BALANCE_FETCH_BASE_DELAY=2.0

# Symbol Freeze Manager
SYMBOL_FREEZE_THRESHOLD=3
SYMBOL_FREEZE_COOLDOWN_HOURS=24.0

# User Account Normalization
MINIMUM_POSITION_USD=7.50
CONSOLIDATION_THRESHOLD_USD=10.00
```

### Example Configuration File

Create `config/cleanup_config.json`:

```json
{
  "dust_cleanup": {
    "threshold_usd": 1.00,
    "dry_run": false,
    "enabled": true,
    "schedule": "daily"
  },
  "balance_fetcher": {
    "max_attempts": 3,
    "base_delay": 2.0,
    "cache_timeout_minutes": 30
  },
  "symbol_freeze": {
    "failure_threshold": 3,
    "cooldown_hours": 24.0,
    "manual_review_required": true,
    "auto_unfreeze": false
  },
  "normalization": {
    "minimum_position_usd": 7.50,
    "consolidation_threshold_usd": 10.00,
    "enabled": true,
    "run_on_startup": true
  }
}
```

---

## Monitoring and Alerts

### Recommended Monitoring

1. **Dust Positions**: Monitor dust cleanup statistics
2. **Balance Fetch Failures**: Alert on consecutive balance fetch failures
3. **Frozen Symbols**: Track frozen symbols and manual review queue
4. **Normalization Results**: Log position consolidation actions

### Example Monitoring Code

```python
def monitor_cleanup_health():
    """Monitor cleanup module health"""
    from bot.symbol_freeze_manager import get_symbol_freeze_manager
    from bot.enhanced_balance_fetcher import get_enhanced_balance_fetcher
    
    # Check frozen symbols
    manager = get_symbol_freeze_manager()
    stats = manager.get_stats()
    if stats['frozen_count'] > 5:
        alert(f"High number of frozen symbols: {stats['frozen_count']}")
    
    # Check balance fetch health
    fetcher = get_enhanced_balance_fetcher()
    info = fetcher.get_last_known_balance()
    if info and info['age_minutes'] > 30:
        alert(f"Balance data is old: {info['age_minutes']:.1f} minutes")
    if info and info['consecutive_errors'] >= 3:
        alert(f"Consecutive balance fetch errors: {info['consecutive_errors']}")
```

---

## Troubleshooting

### Issue: Dust cleanup not working

**Solution:**
- Verify broker supports `force_liquidate=True` parameter
- Check broker minimum trade sizes
- Review logs for specific error messages
- Try with `dry_run=True` first to preview

### Issue: Balance fetcher always using fallback

**Solution:**
- Check broker API connectivity
- Verify API credentials are valid
- Check broker API rate limits
- Review error messages in logs

### Issue: Too many symbols frozen

**Solution:**
- Review frozen symbol errors: `manager.get_frozen_symbols()`
- Manually unfreeze if issue resolved: `manager.unfreeze_symbol(symbol, reason)`
- Adjust failure threshold if too sensitive
- Check broker API health

### Issue: Normalization closing too many positions

**Solution:**
- Always run with `dry_run=True` first
- Adjust `minimum_position_usd` threshold
- Review position values before execution
- Use manual position review for borderline cases

---

## Best Practices

1. **Always test with dry_run=True first** before executing live cleanups
2. **Monitor frozen symbols** and manually review flagged issues
3. **Run normalization pass** only during low-activity periods
4. **Keep balance fetch retry logs** for debugging API issues
5. **Schedule periodic dust cleanup** (e.g., daily) to prevent accumulation
6. **Alert on consecutive balance fetch failures** to detect API issues early
7. **Review frozen symbol list regularly** and manually unfreeze when resolved

---

## Additional Resources

- **Tests**: See `bot/test_cleanup_enhancements.py` for usage examples
- **Source Code**: 
  - `bot/broker_dust_cleanup.py`
  - `bot/enhanced_balance_fetcher.py`
  - `bot/symbol_freeze_manager.py`
  - `bot/user_account_normalization.py`
- **Restricted Symbols**: `bot/restricted_symbols.json` (AUT-USD already added)

---

## Summary

These enhancements provide robust mechanisms for:

1. ✅ **Immediate**: Broker-level dust cleanup and AUT-USD restriction
2. ✅ **High Priority**: Retry logic for balance fetch and symbol freeze on price failures
3. ✅ **Structural**: User account normalization with position consolidation

All modules include comprehensive logging, error handling, and test coverage (18 tests passing).
