# Legacy Position Exit Protocol - Quick Reference

## What It Does

Brings every account to a **clean, strategy-aligned state** by:
1. ✅ Classifying all positions (Strategy-Aligned, Legacy, or Zombie)
2. 🧹 Cancelling stale open orders to free capital
3. 🎯 Controlled exits using intelligent strategies
4. ✅ Verifying clean state

## Quick Start

### Verify Current State
```bash
python run_legacy_exit_protocol.py --verify-only
```

### Run Full Cleanup
```bash
python run_legacy_exit_protocol.py --broker coinbase
```

### Dry Run (Simulate)
```bash
python run_legacy_exit_protocol.py --dry-run
```

## Position Categories

| Category | Description | Action |
|----------|-------------|--------|
| **Strategy-Aligned** ✅ | Has entry price, tracker registered, within cap | Let strategy manage |
| **Legacy Non-Compliant** ⚠️ | Missing tracker, wrong sizing, external | Gradual 25% unwind |
| **Zombie** ❌ | Unknown symbol, no price, dust (< $1 or 1%) | Immediate market close |

## Exit Strategies

### Rule 1: Dust (< 1% of account)
→ **Market close immediately**
- Small slippage doesn't matter

### Rule 2: Over-Cap
→ **Close worst performing first**
- Ranked by: smallest USD → worst P&L → oldest

### Rule 3: Legacy Non-Compliant
→ **Gradual unwind: 25% per cycle over 4 cycles**
- State persists across restarts

### Rule 4: Zombie
→ **Try market exit once**
- If fails → log + escalate (don't halt trading)

## Clean State Criteria

Account is **CLEAN** when:
- ✅ Positions ≤ cap (default: 8)
- ✅ No zombie positions
- ✅ All positions registered in tracker
- ✅ No stale open orders (> 30 min)

## CLI Options

```bash
# Basic usage
python run_legacy_exit_protocol.py [options]

# Options
--broker BROKER         # coinbase, kraken, alpaca [default: coinbase]
--max-positions N       # Maximum positions [default: 8]
--dust-pct PCT          # Dust threshold % [default: 0.01 = 1%]
--stale-minutes MIN     # Stale order age [default: 30]
--user-id ID            # User ID for multi-account
--dry-run               # Simulate without trades
--phase PHASE           # Run specific phase (1, 2, 3, 4, or 'all')
--verify-only           # Only run verification (no trades)

# Examples
python run_legacy_exit_protocol.py --verify-only
python run_legacy_exit_protocol.py --phase 2  # Order cleanup only
python run_legacy_exit_protocol.py --max-positions 10 --dry-run
```

## Integration Options

### 1. Startup Verification
```python
from example_legacy_protocol_integration import integrate_with_bot_startup

# Verify on startup
is_clean = integrate_with_bot_startup(verify_only=True)
if not is_clean:
    logger.warning("Account needs cleanup")
```

### 2. Recurring Task (Every 6 Hours)
```python
from example_legacy_protocol_integration import integrate_as_recurring_task

# Add to scheduler
result = integrate_as_recurring_task(interval_hours=6)
```

### 3. Inline Check (Every N Cycles)
```python
from example_legacy_protocol_integration import integrate_with_trading_loop

cycle_count = 0
while trading:
    # Trading logic...
    
    cycle_count += 1
    if cycle_count % 10 == 0:
        if not integrate_with_trading_loop():
            logger.warning("Cleanup needed")
```

### 4. Manual Trigger
```python
from example_legacy_protocol_integration import manual_cleanup_trigger

# Trigger cleanup
result = manual_cleanup_trigger(broker_name='coinbase', user_id='user123')
```

### 5. REST API
```python
from flask import Flask
from example_legacy_protocol_integration import create_cleanup_api_endpoint

app = Flask(__name__)
create_cleanup_api_endpoint(app, 'coinbase')

# Endpoints:
# GET  /api/cleanup/verify?user_id=123
# POST /api/cleanup/execute {"user_id": "123", "max_positions": 8}
```

## State Tracking

State is saved to `data/legacy_exit_protocol_state.json`:

```json
{
  "account_state": "CLEAN",
  "unwind_progress": {
    "ETH-USD": {
      "cycle": 2,
      "remaining_pct": 0.5625,
      "started_at": "2026-02-18T22:00:00"
    }
  },
  "cleanup_metrics": {
    "total_positions_cleaned": 15,
    "zombie_positions_closed": 5,
    "legacy_positions_unwound": 8,
    "stale_orders_cancelled": 12,
    "capital_freed_usd": 247.50
  }
}
```

## Metrics Tracked

- Total positions cleaned
- Zombie positions closed
- Legacy positions unwound
- Stale orders cancelled
- Capital freed (USD)

## Example Workflows

### Daily Maintenance
```bash
# Morning check
python run_legacy_exit_protocol.py --verify-only

# If cleanup needed
python run_legacy_exit_protocol.py --broker coinbase

# Check state file
cat data/legacy_exit_protocol_state.json
```

### Multi-Account Platform
```bash
# Platform account
python run_legacy_exit_protocol.py --broker coinbase

# User accounts
python run_legacy_exit_protocol.py --user-id user_123
python run_legacy_exit_protocol.py --user-id user_456
```

### Scheduled via Cron
```bash
# Add to crontab: Run every 6 hours
0 */6 * * * cd /path/to/Nija && python run_legacy_exit_protocol.py >> logs/cleanup.log 2>&1
```

## Troubleshooting

### "Cannot fetch price" errors
- Zombie position with invalid/delisted symbol
- Will be marked ZOMBIE_LEGACY and exit attempted
- If exit fails, logged for manual intervention

### Over-cap persists
- New positions opened during cleanup
- Check unwind_progress in state file
- May need multiple runs for gradual unwind

### Stale orders not cancelled
- Verify order timestamp format from broker
- Adjust `--stale-minutes` if needed
- Check broker API `get_open_orders()` implementation

## Safety Features

✅ **Non-destructive classification** - Phase 1 only categorizes
✅ **Gradual unwinding** - 25% per cycle, no market shock
✅ **State persistence** - Progress saved across restarts
✅ **Fail-safe zombie handling** - Doesn't halt trading
✅ **Dry run mode** - Test without executing
✅ **Comprehensive logging** - Every decision logged

## Performance Impact

- Classification: < 1 second
- Order cleanup: ~0.1s per order
- Position exits: ~0.5s per position
- Verification: < 1 second

Total typical run: 2-5 seconds

## Testing

Run test suite:
```bash
python test_legacy_exit_protocol.py
```

Expected: 16 tests pass in ~0.01s

## Files

| File | Purpose | Lines |
|------|---------|-------|
| `bot/legacy_position_exit_protocol.py` | Core implementation | 1067 |
| `run_legacy_exit_protocol.py` | CLI interface | 214 |
| `test_legacy_exit_protocol.py` | Test suite | 515 |
| `LEGACY_POSITION_EXIT_PROTOCOL.md` | Full documentation | 350+ |
| `example_legacy_protocol_integration.py` | Integration examples | 328 |

## Next Steps

1. **Verify current state**: `python run_legacy_exit_protocol.py --verify-only`
2. **Test with dry run**: `python run_legacy_exit_protocol.py --dry-run`
3. **Execute cleanup**: `python run_legacy_exit_protocol.py`
4. **Monitor state**: `cat data/legacy_exit_protocol_state.json`
5. **Schedule recurring**: Add to cron or scheduler
6. **Integrate with bot**: Use examples from `example_legacy_protocol_integration.py`

## Support

For issues or questions:
- Check logs for detailed error messages
- Review state file for progress tracking
- Run with `--dry-run` to simulate
- Check test suite to verify functionality
