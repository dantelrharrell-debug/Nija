# Trade Execution Guards - Implementation Guide

> **⚠️ NOTE:** This document contains references to a deprecated copy trading feature.  
> NIJA now uses an independent trading model. See [USER_FAQ.md](USER_FAQ.md) for details.

## Overview

This document describes the P0/P1/P2 guard system implemented to prevent fake positions and improve trade execution reliability.

**Core Principle**: *The execution broker decides reality, not the strategy engine.*

## The Problem

Before these guards, the system had several critical vulnerabilities:

1. **Fake Positions (P0)**: Positions were being created in the ledger even when broker orders failed
2. **Premature Copy Trading (P1)**: Copy trading was triggering on "signal approved" instead of actual filled orders
3. **No Visibility (P2)**: No way to see which users successfully copied a master trade vs. which failed or skipped

## The Solution

### P0: Hard Guard Against Fake Positions

**Location**: `bot/broker_manager.py` line 3074

**Implementation**:
```python
# P0 GUARD: Execution broker decides reality - verify order success before ANY position creation
if not success:
    logger.error("🔴 P0 GUARD: Order failed — aborting position creation")
    logger.error("   Enforcement: No ledger write. No position. No copy trading.")
    return {
        "status": "unfilled",
        "error": "ORDER_FAILED",
        "message": "Broker reported order failure"
    }
```

**What it prevents**:
- ❌ Ledger writes when broker orders fail
- ❌ Position tracking when broker orders fail
- ❌ Copy trading signals when broker orders fail

**Result**: Only positions backed by real broker orders are created.

---

### P1: Copy Trading Only on Filled Orders

**Location**: `bot/trade_signal_emitter.py` lines 204-210

**Implementation**:
```python
# P1: Verify order is filled before emitting signal
if order_status not in ["FILLED", "PARTIALLY_FILLED"]:
    logger.warning(f"⚠️  Signal NOT emitted - order status is {order_status}")
    logger.warning(f"   Copy trading requires confirmed filled orders")
    return False
```

**What it enforces**:
- ✅ Signals only emit for FILLED orders
- ✅ Signals only emit for PARTIALLY_FILLED orders
- ❌ No signals for PENDING orders
- ❌ No signals for APPROVED orders
- ❌ No signals for any other status

**Consistency**: Copy trade engine (`bot/copy_trade_engine.py` line 408) enforces the same check when receiving orders.

**Result**: Copy trading only triggers when master orders are actually executed by the broker.

---

### P2: Trade Map for User Visibility

**Location**: `bot/trade_ledger_db.py`

**Database Schema**:
```sql
CREATE TABLE copy_trade_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_trade_id TEXT NOT NULL,
    master_user_id TEXT DEFAULT 'master',
    master_symbol TEXT NOT NULL,
    master_side TEXT NOT NULL,
    master_order_id TEXT,
    master_timestamp TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_status TEXT NOT NULL,  -- 'filled', 'skipped', 'failed'
    user_order_id TEXT,
    user_error TEXT,
    user_size REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
```

**User Statuses**:
1. **filled**: User's order successfully executed
   - Records: user_order_id, user_size

2. **skipped**: User doesn't have the broker configured or broker not connected
   - Records: user_error explaining why

3. **failed**: User's order execution failed
   - Records: user_error with failure reason

**API Methods**:

```python
from bot.trade_ledger_db import get_trade_ledger_db

db = get_trade_ledger_db()

# Record a copy trade execution
db.record_copy_trade(
    master_trade_id='coinbase_BTC-USD_order123_1234567890',
    master_symbol='BTC-USD',
    master_side='buy',
    master_order_id='order123',
    user_id='daivon',
    user_status='filled',
    user_order_id='user_order_456',
    user_size=100.0
)

# Get all copy executions for a master trade
trade_map = db.get_copy_trade_map(master_trade_id='coinbase_BTC-USD_order123_1234567890')

# Get summary statistics
summary = db.get_copy_trade_summary(master_trade_id='coinbase_BTC-USD_order123_1234567890')
# Returns: {'total_users': 3, 'filled_count': 1, 'skipped_count': 1, 'failed_count': 1, ...}
```

**Result**: Full transparency and debugging power for copy trading.

---

## Usage Examples

### Example 1: Viewing Trade Map

```python
from bot.trade_ledger_db import get_trade_ledger_db

db = get_trade_ledger_db()

# Get copy trade map for a specific master trade
master_trade_id = 'coinbase_BTC-USD_abc123_1737497436'
trade_map = db.get_copy_trade_map(master_trade_id)

print(f"Master Trade: {master_trade_id}")
print(f"Copy Executions:")
for execution in trade_map:
    print(f"  User: {execution['user_id']}")
    print(f"  Status: {execution['user_status']}")
    if execution['user_status'] == 'filled':
        print(f"  Order ID: {execution['user_order_id']}")
        print(f"  Size: ${execution['user_size']:.2f}")
    elif execution['user_status'] in ['skipped', 'failed']:
        print(f"  Reason: {execution['user_error']}")
    print()
```

**Output**:
```
Master Trade: coinbase_BTC-USD_abc123_1737497436
Copy Executions:
  User: daivon
  Status: filled
  Order ID: user_order_456
  Size: $100.00

  User: tania
  Status: skipped
  Reason: No Coinbase account

  User: investor3
  Status: failed
  Reason: Insufficient funds
```

### Example 2: Dashboard Integration

```python
from bot.trade_ledger_db import get_trade_ledger_db

db = get_trade_ledger_db()

# Get recent master trades with copy execution summary
recent_trades = db.get_ledger_transactions(user_id='master', limit=10)

for trade in recent_trades:
    master_trade_id = trade['order_id']  # or use trade['master_trade_id']

    # Get copy trade summary
    summary = db.get_copy_trade_summary(master_trade_id)

    print(f"Trade: {trade['symbol']} {trade['side']} @ ${trade['price']:.2f}")
    print(f"  Total Users: {summary['total_users']}")
    print(f"  ✅ Filled: {summary['filled_count']}")
    print(f"  ⏭️  Skipped: {summary['skipped_count']}")
    print(f"  ❌ Failed: {summary['failed_count']}")
    print()
```

---

## Testing

### Running Tests

```bash
python test_p0_p1_p2_guards.py
```

**Test Coverage**:
- ✅ P0: Position creation guard (verified via code inspection)
- ✅ P1: Signal emission guards (FILLED/PARTIALLY_FILLED accepted, others rejected)
- ✅ P2: Trade map schema, recording, and querying

**Security**:
- ✅ CodeQL scan: 0 vulnerabilities
- ✅ SQL injection: Protected via parameterized queries
- ✅ Input validation: All user inputs validated

---

## Migration Guide

### For Existing Deployments

The changes are **backward compatible**:

1. **Database Migration**: Automatic on first run
   - `copy_trade_map` table created automatically
   - `master_trade_id` column added to `trade_ledger` (nullable)

2. **Code Changes**: Drop-in replacement
   - Existing code continues to work
   - New guards add extra safety
   - Trade map is optional (won't break if trade_ledger unavailable)

3. **No Action Required**:
   - Position tracking continues as before (but now safer)
   - Copy trading continues as before (but now more reliable)
   - Trade map starts recording from deployment forward

---

## Monitoring

### Key Metrics to Track

1. **P0 Guard Triggers**:
   - Look for "P0 GUARD: Order failed — aborting position creation" in logs
   - Indicates broker orders failing (expected, guard is working)

2. **P1 Guard Rejections**:
   - Look for "Signal NOT emitted - order status is X" warnings
   - Indicates non-filled orders being rejected (expected, guard is working)

3. **P2 Trade Map**:
   - Query `copy_trade_map` table to see copy execution rates
   - Monitor `filled_count` vs `total_users` ratio

### Example Monitoring Query

```python
from bot.trade_ledger_db import get_trade_ledger_db

db = get_trade_ledger_db()

# Get copy success rate for recent trades
with db._get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(DISTINCT master_trade_id) as total_master_trades,
            SUM(CASE WHEN user_status = 'filled' THEN 1 ELSE 0 END) as total_filled,
            SUM(CASE WHEN user_status = 'skipped' THEN 1 ELSE 0 END) as total_skipped,
            SUM(CASE WHEN user_status = 'failed' THEN 1 ELSE 0 END) as total_failed,
            COUNT(*) as total_copy_attempts
        FROM copy_trade_map
        WHERE created_at >= datetime('now', '-1 day')
    """)
    stats = dict(cursor.fetchone())

print(f"Last 24 Hours Copy Trading Stats:")
print(f"  Master Trades: {stats['total_master_trades']}")
print(f"  Copy Attempts: {stats['total_copy_attempts']}")
print(f"  ✅ Filled: {stats['total_filled']}")
print(f"  ⏭️  Skipped: {stats['total_skipped']}")
print(f"  ❌ Failed: {stats['total_failed']}")
print(f"  Success Rate: {stats['total_filled'] / stats['total_copy_attempts'] * 100:.1f}%")
```

---

## Troubleshooting

### Problem: P0 Guard Triggering Frequently

**Symptoms**: Seeing many "P0 GUARD: Order failed" errors

**Diagnosis**:
1. Check broker API status
2. Verify account has sufficient balance
3. Check for API rate limiting

**Solution**: Fix root cause (balance, API issues, etc.)

### Problem: No Copy Trades Executing

**Symptoms**: `filled_count` is always 0 in trade map

**Diagnosis**:
1. Check if P1 guard is rejecting signals (look for warning logs)
2. Verify order_status is being set correctly in broker responses
3. Check if users have broker accounts configured

**Solution**:
- Ensure `order_status='FILLED'` is passed to `emit_trade_signal()`
- Verify broker responses include correct status

### Problem: Trade Map Not Recording

**Symptoms**: `copy_trade_map` table is empty

**Diagnosis**:
1. Check if trade_ledger is initialized in copy_trade_engine
2. Look for "Could not record copy trade in map" warnings
3. Verify database permissions

**Solution**: Check logs for specific errors, ensure database is writable

---

## Rollback Plan

If issues occur, rollback is simple:

1. **P0**: Remove guard at line 3074 in `broker_manager.py`
2. **P1**: Change `emit_trade_signal()` to always return True
3. **P2**: Copy trade engine will continue working (trade map just won't be populated)

**Note**: P0 and P1 are safety features - only rollback if absolutely necessary.

---

## Future Enhancements

### Possible Improvements

1. **Real-time Dashboard**: Live view of copy trade executions
2. **Email Notifications**: Alert users when their copy trades execute/fail
3. **Retry Logic**: Automatically retry failed copy trades
4. **Trade Map Export**: CSV/PDF export of copy trade history
5. **Performance Metrics**: Track copy trade latency

---

## Summary

The P0/P1/P2 guard system ensures:

✅ **P0**: No fake positions - only real broker orders create positions
✅ **P1**: No premature copy trading - only filled orders trigger copies
✅ **P2**: Full visibility - complete audit trail of copy executions

**Result**: A more reliable, transparent, and trustworthy copy trading system.
