# Cleanup Dry-Run Mode Guide

## Overview

The Forced Position Cleanup Engine includes a **dry-run mode** that allows you to simulate cleanup operations without executing actual trades. This is essential for:

1. **Testing cap enforcement logic** before deploying to production
2. **Validating cleanup decisions** without financial risk
3. **Debugging position selection algorithms**
4. **Auditing cleanup behavior** with live data

## Enabling Dry-Run Mode

### Method 1: Constructor Parameter

```python
from bot.forced_position_cleanup import ForcedPositionCleanup

cleanup = ForcedPositionCleanup(
    dust_threshold_usd=1.00,
    max_positions=8,
    dry_run=True  # Enable dry-run mode
)

# Run cleanup
cleanup.run_cleanup_all_accounts(broker_manager)
```

### Method 2: Environment Variable

Set in your `.env` file or environment:

```bash
FORCED_CLEANUP_DRY_RUN=true
```

Then initialize without explicit parameter:

```python
cleanup = ForcedPositionCleanup()  # Will read from environment
```

### Method 3: Command-Line Script

Run the provided cleanup script in dry-run mode:

```bash
python run_forced_cleanup.py --dry-run
```

## What Happens in Dry-Run Mode

When dry-run is enabled, the cleanup engine:

1. ✅ **Queries all positions** from brokers (real data)
2. ✅ **Identifies cleanup targets** (dust positions, cap excess)
3. ✅ **Logs planned actions** with `[DRY RUN]` prefix
4. ✅ **Generates cap violation alerts** if limits exceeded
5. ❌ **Does NOT close positions** (no actual trades)
6. ❌ **Does NOT cancel open orders** (no order modifications)

### Example Output

```
🧹 [CAP_EXCEEDED][FORCED] BTC-USD
   Account: user_john_KRAKEN
   Reason: Position cap exceeded (10/8)
   Size: $150.00
   P&L: -2.50%
   PROFIT_STATUS = PENDING → CONFIRMED
   OUTCOME = LOSS
   [DRY RUN][WOULD_CLOSE] Position

🧹 Cleanup executed: user_john_KRAKEN
   Successful: 2 (simulated)
   Failed: 0
```

## Verification Steps

### 1. Pre-Cleanup Check

Before running dry-run, capture current state:

```bash
# Get current position count
python -c "from bot.broker_manager import get_all_brokers; \
           brokers = get_all_brokers(); \
           print(f'Current positions: {sum(len(b.get_positions()) for b in brokers)}')"
```

### 2. Run Dry-Run Cleanup

```bash
python run_forced_cleanup.py --dry-run 2>&1 | tee cleanup-dryrun.log
```

### 3. Review Logs

Check the log file for:

- **Cap violation alerts**: `🚨 CAP_VIOLATION_ALERT`
- **Positions to be closed**: `[DRY RUN][WOULD_CLOSE]`
- **Order cancellations**: `[DRY RUN][OPEN_ORDER][WOULD_CANCEL]`

### 4. Validate Decisions

Verify that cleanup decisions are correct:

```python
# Example: Check which positions would be closed
import re

with open('cleanup-dryrun.log', 'r') as f:
    log_content = f.read()
    
# Extract positions that would be closed
would_close = re.findall(r'\[DRY RUN\]\[WOULD_CLOSE\].*?Symbol: (\S+)', log_content)
print(f"Would close {len(would_close)} positions: {would_close}")
```

### 5. Post-Check (Verify No Changes)

After dry-run, positions should be unchanged:

```bash
# Verify positions unchanged
python -c "from bot.broker_manager import get_all_brokers; \
           brokers = get_all_brokers(); \
           print(f'Current positions: {sum(len(b.get_positions()) for b in brokers)}')"
```

Should match pre-cleanup count.

## Common Use Cases

### Use Case 1: Test Cap Enforcement

```python
# Simulate cleanup with lower cap to see what would be closed
cleanup = ForcedPositionCleanup(
    max_positions=5,  # Lower than current
    dry_run=True
)

cleanup.run_cleanup_all_accounts(broker_manager)
# Review logs to see which positions would be closed
```

### Use Case 2: Validate Dust Detection

```python
# Check what qualifies as dust
cleanup = ForcedPositionCleanup(
    dust_threshold_usd=1.00,
    dry_run=True
)

# Get dust positions (without closing them)
for broker in brokers:
    positions = broker.get_positions()
    dust = cleanup.identify_dust_positions(positions)
    print(f"Dust positions on {broker.name}: {len(dust)}")
    for pos in dust:
        print(f"  - {pos['symbol']}: ${pos['size_usd']:.2f}")
```

### Use Case 3: Audit Per-User Cap Enforcement

```python
# Test per-user cleanup logic
cleanup = ForcedPositionCleanup(
    max_positions=8,
    dry_run=True
)

# Simulate cleanup for specific user
user_brokers = {
    BrokerType.KRAKEN: kraken_broker,
    BrokerType.COINBASE: coinbase_broker
}

cleanup._cleanup_user_all_brokers(
    user_id="john_doe",
    user_broker_dict=user_brokers,
    is_startup=False
)
```

## Safety Features

Dry-run mode includes several safety features:

1. **Explicit Logging**: Every action is logged with `[DRY RUN]` prefix
2. **No Side Effects**: No positions closed, no orders cancelled
3. **Real Data**: Uses actual position data for accurate simulation
4. **Alert Generation**: Cap violations still trigger alerts
5. **Failure Tracking**: Simulates failures to test error handling

## Transitioning to Live Mode

Once dry-run validation is complete:

1. **Review all logs** for unexpected behavior
2. **Verify cap settings** are correct
3. **Confirm dust threshold** is appropriate
4. **Check broker connections** are stable
5. **Set `dry_run=False`** to enable live cleanup

```python
# After validation, switch to live mode
cleanup = ForcedPositionCleanup(
    dust_threshold_usd=1.00,
    max_positions=8,
    dry_run=False  # Live mode - WILL CLOSE POSITIONS
)
```

⚠️ **Warning**: Once `dry_run=False`, cleanup will execute real trades!

## Monitoring Dry-Run Results

### Log Analysis

```bash
# Count simulated closures
grep -c "\[DRY RUN\]\[WOULD_CLOSE\]" cleanup-dryrun.log

# Count simulated order cancellations
grep -c "\[DRY RUN\].*\[WOULD_CANCEL\]" cleanup-dryrun.log

# Find cap violations
grep "CAP_VIOLATION_ALERT" cleanup-dryrun.log
```

### JSON Export (Optional)

For programmatic analysis, export dry-run results:

```python
import json

results = {
    'timestamp': datetime.now().isoformat(),
    'dry_run': True,
    'positions_would_close': [],
    'orders_would_cancel': []
}

# Populate from cleanup results
with open('cleanup-dryrun-results.json', 'w') as f:
    json.dump(results, f, indent=2)
```

## Troubleshooting

### Issue: Dry-run closes positions anyway

**Cause**: `dry_run` parameter not set correctly

**Solution**: Verify parameter:
```python
assert cleanup.dry_run == True, "Dry-run not enabled!"
```

### Issue: No output in dry-run

**Cause**: No positions meet cleanup criteria

**Solution**: Lower thresholds to test:
```python
cleanup = ForcedPositionCleanup(
    dust_threshold_usd=10000.00,  # High threshold for testing
    max_positions=1,               # Low cap for testing
    dry_run=True
)
```

### Issue: Can't find dry-run logs

**Cause**: Logs not captured

**Solution**: Redirect output:
```bash
python run_forced_cleanup.py --dry-run 2>&1 | tee cleanup-dryrun.log
```

## Best Practices

1. **Always test in dry-run first** before enabling live cleanup
2. **Save dry-run logs** for audit trail
3. **Compare multiple dry-runs** to ensure consistency
4. **Test with various cap values** to understand impact
5. **Monitor for false positives** (positions incorrectly flagged)
6. **Validate broker responses** (ensure data is accurate)

## Related Documentation

- `FORCED_CLEANUP_GUIDE.md` - General cleanup documentation
- `POSITION_CAP_ENFORCEMENT_VERIFICATION.md` - Cap enforcement details
- `CLEANUP_ENHANCEMENTS_GUIDE.md` - Advanced cleanup features

## Example Workflow

```bash
# 1. Capture current state
python user_status_summary.py > pre-cleanup-state.txt

# 2. Run dry-run cleanup
python run_forced_cleanup.py --dry-run 2>&1 | tee cleanup-dryrun.log

# 3. Analyze results
grep "WOULD_CLOSE" cleanup-dryrun.log
grep "CAP_VIOLATION" cleanup-dryrun.log

# 4. Verify no changes
python user_status_summary.py > post-dryrun-state.txt
diff pre-cleanup-state.txt post-dryrun-state.txt  # Should be identical

# 5. If satisfied, run live cleanup
python run_forced_cleanup.py  # No --dry-run flag
```

## Summary

Dry-run mode is a **critical safety feature** that allows you to:

✅ Test cleanup logic without risk  
✅ Validate position selection  
✅ Audit cap enforcement  
✅ Debug issues safely  
✅ Generate alerts for monitoring  

**Always use dry-run mode first** before enabling live cleanup in production!
