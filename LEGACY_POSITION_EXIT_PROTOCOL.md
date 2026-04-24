# Legacy Position Exit Protocol

## Overview

The Legacy Position Exit Protocol is a comprehensive system to bring every account to a clean, strategy-aligned state without chaos. It implements a 4-phase approach to classify, clean up, and exit legacy positions systematically.

## Problem Statement

Trading accounts can accumulate problematic positions over time:
- Positions opened outside the system (manual trades, external bots)
- Zombie positions (unknown assets, missing data, dust)
- Over-cap situations (too many positions)
- Stale open orders locking capital
- Missing entry price tracking

This protocol provides a systematic solution to clean up these situations.

## Four-Phase Approach

### Phase 1: Position Classification (Non-Destructive)

Every open position is categorized into one of three categories:

#### Category A — Strategy-Aligned ✅
Let strategy manage normally. Requirements:
- Has entry price tracked
- Known symbol
- Within position cap
- Tracker registered
- Valid stop/exit logic

#### Category B — Valid but Non-Compliant ⚠️
Mark as `LEGACY_NON_COMPLIANT`. Characteristics:
- Missing tracker
- Over cap
- Wrong sizing
- Opened outside system (manual, external bot)

#### Category C — Broken/Zombie ❌
Mark as `ZOMBIE_LEGACY`. Characteristics:
- Unknown asset pair
- Missing entry price
- Cannot fetch price
- Dust position (< $1 or < 1% of account)
- API mismatch

### Phase 2: Order Cleanup (Immediate Safe Action)

**Cancel ALL open limit orders older than X minutes** (default: 30 minutes)

Benefits:
- Frees locked capital
- Reduces exposure complexity
- Clears stale orders that may never fill

Example: $52 held in open orders → freed for active trading

### Phase 3: Controlled Exit Engine

Four intelligent exit rules:

#### Rule 1: Dust Threshold
**If position value < 1% of account balance:**
→ Market close immediately

Small slippage doesn't matter on tiny positions.

#### Rule 2: Over-Cap Positions
**If account exceeds max position cap:**
→ Close worst-performing legacy position first

Ranking criteria:
1. Smallest USD value (minimize capital impact)
2. Worst P&L (cut losers first)
3. Oldest age

#### Rule 3: Non-Compliant Legacy
**For Category B positions:**

Option A (Conservative):
- Attach emergency stop
- Let it exit via signal or stop

Option B (Clean Slate - Implemented):
- Gradual unwind over 3-5 cycles
- Close 25% per cycle
- Track progress across bot restarts

#### Rule 4: Zombie Positions
**Immediate action for Category C:**
- Try market exit once
- If fails → log + escalate
- Do not halt trading thread

### Phase 4: Clean State Verification

Account is considered **CLEAN** when:
- ✅ Positions ≤ cap
- ✅ No zombie positions
- ✅ All positions registered in tracker
- ✅ No stale open orders

Only then mark: `ACCOUNT_STATE = CLEAN`

## Usage

### Command Line Interface

```bash
# Run full protocol on Coinbase
python run_legacy_exit_protocol.py --broker coinbase

# Verify clean state only (no trades)
python run_legacy_exit_protocol.py --verify-only

# Run Phase 2 (order cleanup) only
python run_legacy_exit_protocol.py --phase 2

# Dry run with custom settings
python run_legacy_exit_protocol.py --max-positions 10 --dust-pct 0.02 --dry-run

# Run on specific user account
python run_legacy_exit_protocol.py --user-id user123
```

### Programmatic Usage

```python
from bot.position_tracker import PositionTracker
from bot.broker_integration import get_broker_integration
from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol

# Initialize
position_tracker = PositionTracker()
broker = get_broker_integration('coinbase')

protocol = LegacyPositionExitProtocol(
    position_tracker=position_tracker,
    broker_integration=broker,
    max_positions=8,
    dust_pct_threshold=0.01,  # 1% of account
    stale_order_minutes=30
)

# Run full protocol
results = protocol.run_full_protocol()

# Or run individual phases
classified = protocol.classify_all_positions(positions, account_balance)
cancelled, freed = protocol.cancel_stale_orders()
exit_results = protocol.execute_controlled_exits(classified, account_balance)
state, diagnostics = protocol.verify_clean_state()
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_positions` | 8 | Maximum allowed positions per account |
| `dust_pct_threshold` | 0.01 (1%) | Position value as % of account to consider dust |
| `stale_order_minutes` | 30 | Age in minutes to consider orders stale |
| `gradual_unwind_pct` | 0.25 (25%) | Percentage to close per unwind cycle |
| `unwind_cycles` | 4 | Number of cycles for gradual unwind (3-5) |

## State Persistence

The protocol maintains state across bot restarts in `data/legacy_exit_protocol_state.json`:

```json
{
  "account_state": "CLEAN",
  "classified_positions": {},
  "unwind_progress": {
    "ETH-USD": {
      "cycle": 2,
      "remaining_pct": 0.5625,
      "started_at": "2026-02-18T22:00:00",
      "last_cycle_at": "2026-02-18T22:05:00"
    }
  },
  "last_cleanup_run": "2026-02-18T22:10:00",
  "cleanup_metrics": {
    "total_positions_cleaned": 15,
    "zombie_positions_closed": 5,
    "legacy_positions_unwound": 8,
    "stale_orders_cancelled": 12,
    "capital_freed_usd": 247.50
  }
}
```

## Integration with Existing Systems

### With ForcedPositionCleanup
The Legacy Position Exit Protocol complements the existing `ForcedPositionCleanup`:

- **ForcedPositionCleanup**: Aggressive dust cleanup and cap enforcement
- **LegacyPositionExitProtocol**: Intelligent classification and gradual unwinding

Use together for comprehensive cleanup:
```python
# Run legacy protocol first for classification
protocol.run_full_protocol()

# Then use forced cleanup for any remaining issues
forced_cleanup = ForcedPositionCleanup()
forced_cleanup.cleanup_positions()
```

### With PositionTracker
Integrates seamlessly with existing position tracking:
- Uses `position_tracker.get_position()` to check registration
- Leverages `entry_price` and `position_source` metadata
- Respects existing position management

### Multi-Account Support
Both platform and user accounts supported via `user_id` parameter:
```python
# Platform account
protocol.run_full_protocol(user_id=None)

# User account
protocol.run_full_protocol(user_id="user123")
```

## Monitoring & Metrics

Track cleanup effectiveness through metrics:
- Total positions cleaned
- Zombie positions closed
- Legacy positions unwound
- Stale orders cancelled
- Capital freed (USD)

Logs include structured alerts for monitoring systems:
```python
{
  'timestamp': '2026-02-18T22:00:00',
  'alert_type': 'POSITION_CAP_VIOLATION',
  'severity': 'CRITICAL',
  'user_id': 'platform',
  'current_count': 12,
  'max_positions': 8,
  'excess_count': 4
}
```

## Safety Features

1. **Non-Destructive Classification**: Phase 1 only categorizes, doesn't trade
2. **Gradual Unwinding**: Legacy positions closed 25% at a time over multiple cycles
3. **Fail-Safe Zombie Handling**: Failed zombie exits don't halt trading
4. **State Persistence**: Progress saved across restarts
5. **Dry Run Mode**: Test protocol without executing trades
6. **Comprehensive Logging**: Every decision logged for audit

## Testing

Run the comprehensive test suite:
```bash
python test_legacy_exit_protocol.py
```

Tests cover:
- Position classification logic
- Order cleanup
- Controlled exit strategies
- Clean state verification
- Full protocol execution

## Best Practices

1. **Run Verification First**: Always check current state before cleanup
   ```bash
   python run_legacy_exit_protocol.py --verify-only
   ```

2. **Test with Dry Run**: Simulate cleanup before executing
   ```bash
   python run_legacy_exit_protocol.py --dry-run
   ```

3. **Monitor Progress**: Check state file for gradual unwind progress
   ```bash
   cat data/legacy_exit_protocol_state.json
   ```

4. **Schedule Regular Runs**: Add to cron or scheduler
   ```bash
   # Run cleanup daily at 2 AM
   0 2 * * * cd /path/to/Nija && python run_legacy_exit_protocol.py
   ```

5. **Review Metrics**: Track cleanup effectiveness over time

## Troubleshooting

### "Cannot fetch price" errors
- Zombie positions with delisted or invalid symbols
- Protocol will mark as ZOMBIE_LEGACY and attempt exit
- If exit fails, position is logged for manual intervention

### Over-cap persists after cleanup
- Check for new positions opened during cleanup
- Verify broker API returns accurate position count
- Review unwind_progress for incomplete cycles

### Stale orders not cancelled
- Verify order creation timestamp format
- Check broker API `get_open_orders()` implementation
- Adjust `stale_order_minutes` if needed

## Security Considerations

- Protocol requires broker API credentials (same as main bot)
- No credentials stored in state file
- All trades executed through existing broker integration
- Dry run mode for testing without real trades

## Future Enhancements

Potential improvements:
- [ ] Machine learning for position health scoring
- [ ] Adaptive unwind percentages based on volatility
- [ ] Multi-exchange atomic cleanup
- [ ] Automated escalation for failed zombie exits
- [ ] Integration with monitoring/alerting systems
- [ ] Web dashboard for cleanup visualization

## References

- `bot/legacy_position_exit_protocol.py` - Core implementation
- `run_legacy_exit_protocol.py` - CLI interface
- `test_legacy_exit_protocol.py` - Test suite
- `bot/forced_position_cleanup.py` - Existing cleanup system
- `bot/position_tracker.py` - Position tracking integration
