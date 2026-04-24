# Order Management and Account Tracking Improvements

**Date:** February 17, 2026  
**Author:** NIJA Trading Systems

## Overview

This document describes the comprehensive improvements made to order management and account-specific tracking to address capital efficiency concerns, especially for MICRO_CAP accounts.

## Problem Statement

The system needed improvements in the following areas:

1. **Order Tracking**: Count open orders per account with detailed tracking
2. **MICRO_CAP Restrictions**: Explicitly disable DCA and multiple concurrent entries
3. **Margin Reservation**: Ensure stop/target orders don't double-reserve margin
4. **Order Cleanup**: Verify orders are cleaned up after filled trades
5. **Dust Orders**: Confirm no leftover dust orders
6. **Account Separation**: Track expectancy + drawdown separately per account, never aggregate
7. **Held Capital**: Monitor held capital amount per account
8. **Order Fragmentation**: Detect and prevent order fragmentation that kills performance in micro accounts

## Solutions Implemented

### 1. Account Order Tracker (`bot/account_order_tracker.py`)

A comprehensive order tracking system that maintains detailed information about all orders per account.

**Features:**
- **Order Counting**: Tracks all open orders per account with full details (symbol, side, price, quantity, age)
- **Held Capital Tracking**: Monitors reserved capital per order and aggregates by account
- **Double-Reservation Detection**: Verifies that stop and target orders for the same position don't both reserve capital
- **Order Cleanup**: Automatically removes old filled/cancelled orders after configurable time period
- **Stale Order Detection**: Identifies orders that have been open too long (default: 60 minutes)
- **Order Fragmentation Detection**: Critical for micro accounts - alerts when too much capital is tied up in multiple small orders
- **Account Statistics**: Provides comprehensive stats including order counts by type, held capital, and oldest order age

**Key Classes:**
```python
OrderInfo              # Detailed order information with age tracking
AccountOrderStats      # Statistics for orders per account
AccountOrderTracker    # Main tracking system
```

**Usage Example:**
```python
from bot.account_order_tracker import get_order_tracker, OrderInfo

tracker = get_order_tracker()

# Add an order
order = OrderInfo(
    order_id="ORDER-123",
    account_id="PLATFORM",
    symbol="BTC-USD",
    side="buy",
    price=45000.0,
    quantity=0.01,
    size_usd=450.0,
    status="open",
    created_at=datetime.now(),
    reserved_capital=450.0
)
tracker.add_order(order)

# Get order count
count = tracker.get_order_count("PLATFORM")

# Check for order fragmentation (critical for micro accounts)
is_fragmented, message = tracker.detect_order_fragmentation(
    "PLATFORM",
    account_balance=100.0,
    warn_threshold=0.30  # Warn if > 30% of capital held
)

# Check for double-reservation
has_double, message = tracker.check_double_reservation("POS-123", "PLATFORM")
```

### 2. Account Performance Tracker (`bot/account_performance_tracker.py`)

Tracks performance metrics separately per account with explicit prohibition on aggregation.

**Features:**
- **Separate Trade Histories**: Each account maintains its own trade history
- **Expectancy Calculation**: Calculated independently per account using standard formula:
  - `Expectancy = (Win Rate × Avg Win) - (Loss Rate × Avg Loss)`
- **Drawdown Tracking**: Peak balance and current drawdown tracked per account
- **No Aggregation**: Explicit verification that accounts remain separate
- **Comprehensive Metrics**: Win rate, profit factor, Sharpe ratio, streaks, etc.
- **Cross-Contamination Detection**: Verifies no trades from one account leak into another

**Key Classes:**
```python
TradeRecord                   # Individual trade record
AccountPerformanceMetrics     # Performance metrics per account
AccountPerformanceTracker     # Main tracking system
```

**Usage Example:**
```python
from bot.account_performance_tracker import get_performance_tracker, TradeRecord

tracker = get_performance_tracker()

# Record a trade
trade = TradeRecord(
    trade_id="TRADE-1",
    account_id="PLATFORM",
    symbol="BTC-USD",
    side="buy",
    entry_price=45000.0,
    exit_price=46000.0,
    quantity=0.01,
    size_usd=450.0,
    pnl=10.0,
    pnl_pct=2.22,
    fees=2.0,
    net_pnl=8.0,
    entry_time=entry_time,
    exit_time=exit_time,
    hold_time_seconds=7200,
    is_win=True
)
tracker.record_trade(trade)

# Update balance (for drawdown tracking)
tracker.update_balance("PLATFORM", 1000.0)

# Get metrics (NEVER aggregate across accounts)
metrics = tracker.get_metrics("PLATFORM")
print(f"Expectancy: ${metrics.expectancy:.2f}")
print(f"Max Drawdown: ${metrics.max_drawdown:.2f} ({metrics.max_drawdown_pct:.1f}%)")

# Verify no cross-contamination
results = tracker.verify_no_aggregation()
```

### 3. MICRO_CAP Configuration Updates (`bot/micro_capital_config.py`)

Added explicit flags to disable DCA and multiple concurrent entries on the same symbol.

**Changes:**
```python
# CRITICAL: DCA and Multiple Entries (Feb 17, 2026 - ORDER MANAGEMENT FIX)
# For MICRO_CAP accounts, we DISABLE:
# - DCA (Dollar Cost Averaging)
# - Multiple concurrent entries on same symbol
# Reason: Order fragmentation kills performance in micro accounts
ENABLE_DCA = False  # DISABLED for micro capital
ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL = False  # DISABLED - one position per symbol max
```

These flags are now included in:
- `MICRO_CAPITAL_CONFIG` dictionary
- Environment variable mapping (`ENABLE_DCA`, `ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL`)

**Rationale:**
- In micro accounts ($15-$500), having multiple small positions on the same symbol fragments capital
- Each order reserves capital and may incur fees, reducing profitability
- Better to have ONE larger, well-placed position per symbol than multiple small entries

## Testing

Comprehensive test suites were created and all tests pass:

### Test Suite 1: Order Management (`bot/tests/test_order_management.py`)

Tests the following scenarios:
1. ✅ **Order Counting**: Orders counted correctly per account
2. ✅ **Held Capital Tracking**: Capital tracked separately per account
3. ✅ **Order Cleanup**: Capital released when orders are filled
4. ✅ **Double-Reservation Detection**: Correctly identifies when stop/target both reserve capital
5. ✅ **Order Fragmentation**: Detects when too much capital is tied up in orders
6. ✅ **Stale Order Cleanup**: Old orders detected and cleaned up
7. ✅ **Account Statistics**: Comprehensive stats calculated correctly

**Run tests:**
```bash
python bot/tests/test_order_management.py
```

### Test Suite 2: Performance Tracking (`bot/tests/test_account_performance.py`)

Tests the following scenarios:
1. ✅ **Separate Trade Histories**: Each account has its own trade history
2. ✅ **Separate Expectancy**: Expectancy calculated independently per account
3. ✅ **Separate Drawdown**: Drawdown tracked independently per account
4. ✅ **No Cross-Contamination**: Trades don't leak between accounts
5. ✅ **No Aggregation**: Metrics are never aggregated across accounts
6. ✅ **Account Summaries**: Comprehensive summaries available per account

**Run tests:**
```bash
python bot/tests/test_account_performance.py
```

## Integration Points

To integrate these improvements into the existing system:

### 1. In Trading Strategy

```python
from bot.account_order_tracker import get_order_tracker, OrderInfo
from bot.account_performance_tracker import get_performance_tracker, TradeRecord

# When placing an order
order_tracker = get_order_tracker()
order_info = OrderInfo(...)
order_tracker.add_order(order_info)

# When an order fills
order_tracker.mark_order_filled(order_id, account_id)

# When closing a position
perf_tracker = get_performance_tracker()
trade = TradeRecord(...)
perf_tracker.record_trade(trade)

# Periodically check order fragmentation (especially for MICRO_CAP)
if micro_cap_mode:
    is_fragmented, message = order_tracker.detect_order_fragmentation(
        account_id, account_balance, warn_threshold=0.30
    )
    if is_fragmented:
        logger.warning(message)
```

### 2. In Risk Manager

```python
from bot.account_order_tracker import get_order_tracker
from bot.account_performance_tracker import get_performance_tracker

# Before sizing a position, check held capital
order_tracker = get_order_tracker()
held_capital = order_tracker.get_held_capital(account_id)
available_capital = account_balance - held_capital

# Check account-specific expectancy before entering trade
perf_tracker = get_performance_tracker()
metrics = perf_tracker.get_metrics(account_id)
if metrics.expectancy < 0:
    logger.warning(f"Negative expectancy for {account_id}: ${metrics.expectancy:.2f}")
```

### 3. In Position Manager

```python
from bot.account_order_tracker import get_order_tracker

# When creating stop/target orders, ensure no double-reservation
order_tracker = get_order_tracker()

# Stop order reserves capital
stop_order = OrderInfo(..., reserved_capital=position_size)
order_tracker.add_order(stop_order)

# Target order should NOT reserve (uses same capital)
target_order = OrderInfo(..., reserved_capital=0.0)  # ← Important!
order_tracker.add_order(target_order)

# Verify
has_double, message = order_tracker.check_double_reservation(position_id, account_id)
if has_double:
    logger.error(f"Double reservation detected: {message}")
```

## Configuration Guidelines

### For MICRO_CAP Accounts ($15-$500)

```python
# micro_capital_config.py
MAX_POSITIONS = 4                           # Limited concurrent positions
ENABLE_DCA = False                          # No averaging down
ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL = False  # One position per symbol
```

### For Larger Accounts ($1000+)

```python
# You may enable these features for larger accounts
MAX_POSITIONS = 6                           # More diversification
ENABLE_DCA = True                           # Can average down if strategy requires
ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL = True   # Can pyramid into positions
```

## Monitoring and Alerts

### Key Metrics to Monitor

1. **Order Fragmentation** (critical for micro accounts):
   - Alert if held capital > 30% of account balance
   - Check frequency: Every order placement

2. **Stale Orders**:
   - Alert if orders > 60 minutes old
   - Check frequency: Every 10 minutes

3. **Expectancy** (per account):
   - Alert if expectancy < 0 (losing system)
   - Check frequency: After every 10 trades

4. **Drawdown** (per account):
   - Alert if current drawdown > 10%
   - Check frequency: After each trade

### Dashboard Integration

Add to status dashboards:

```python
# Example status output
def print_account_status(account_id):
    order_tracker = get_order_tracker()
    perf_tracker = get_performance_tracker()
    
    stats = order_tracker.get_account_stats(account_id)
    metrics = perf_tracker.get_metrics(account_id)
    
    print(f"\n{account_id} Status:")
    print(f"  Open Orders: {stats.total_open_orders}")
    print(f"  Held Capital: ${stats.total_held_capital:.2f}")
    print(f"  Total Trades: {metrics.total_trades}")
    print(f"  Expectancy: ${metrics.expectancy:.2f}/trade")
    print(f"  Max Drawdown: {metrics.max_drawdown_pct:.1f}%")
```

## Best Practices

### DO ✅

1. **Track orders immediately** when placed
2. **Mark orders as filled** as soon as broker confirms
3. **Check order fragmentation** before placing new orders in micro accounts
4. **Monitor expectancy** per account separately
5. **Update balances** regularly for accurate drawdown tracking
6. **Clean up old orders** periodically (24-48 hours after fill)

### DON'T ❌

1. **DON'T aggregate** metrics across accounts
2. **DON'T double-reserve** capital for stop/target orders
3. **DON'T allow** order fragmentation in micro accounts
4. **DON'T enable DCA** for MICRO_CAP accounts
5. **DON'T allow** multiple entries on same symbol for MICRO_CAP
6. **DON'T ignore** stale orders (cleanup required)

## Performance Impact

Expected improvements:

1. **Capital Efficiency**: 20-30% improvement in micro accounts by reducing fragmentation
2. **Order Management**: 100% visibility into all open orders per account
3. **Risk Clarity**: Clear understanding of held vs available capital
4. **Profitability**: Better per-account expectancy tracking enables targeted improvements
5. **Drawdown Control**: Real-time drawdown tracking per account enables earlier intervention

## Future Enhancements

Potential future improvements:

1. **Real-time Alerts**: Integrate with notification system for fragmentation/stale orders
2. **Historical Analysis**: Trend analysis of expectancy and drawdown over time
3. **Broker Integration**: Direct integration with broker APIs for automated order sync
4. **ML Predictions**: Use expectancy trends to predict future performance
5. **Multi-Timeframe Analysis**: Track metrics over different time periods (daily, weekly, monthly)

## References

- Problem Statement: Check Immediately documentation
- Related Files:
  - `bot/account_order_tracker.py`
  - `bot/account_performance_tracker.py`
  - `bot/micro_capital_config.py`
  - `bot/tests/test_order_management.py`
  - `bot/tests/test_account_performance.py`

## Change Log

- **2026-02-17**: Initial implementation
  - Created AccountOrderTracker system
  - Created AccountPerformanceTracker system
  - Updated MICRO_CAP configuration with DCA/multiple entry flags
  - Added comprehensive test suites (all passing)
