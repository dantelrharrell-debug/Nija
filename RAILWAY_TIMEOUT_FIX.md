# Railway Timeout Fix - Position Liquidation

## Problem
Railway was killing the bot container during startup because position liquidation was taking too long and blocking the main trading loop from starting.

**Timeline:**
- Container starts at 06:20:29Z
- Bot initializes (4 seconds)
- Bot tries to liquidate 6 excess positions
- Liquidation hangs/takes too long
- Railway kills container at ~6 seconds
- Cycle repeats infinitely

## Solution Implemented

### 1. Parameterized Timeout (lines 1806-1820)
```python
def close_excess_positions(self, max_positions=8, timeout_seconds=5):
    # timeout_seconds parameter allows different timeouts for different scenarios
```

**Timeout Strategy:**
- **Startup liquidation**: 20 seconds (deferred to first trading cycle, not __init__)
- **Mid-cycle liquidation**: 10 seconds (emergency check during run_cycle)
- **Default**: 5 seconds (fallback safety)

### 2. Deferred Liquidation
Liquidation is deferred from __init__ to first run_cycle() call to avoid Railway timeout during startup.

**Before:**
```
Container starts → __init__ tries to liquidate → Hangs → Railway kills
```

**After:**
```
Container starts → __init__ defers → Main loop starts immediately → 
First cycle liquidates with safety timeout
```

### 3. Graceful Timeout Handling (in close_excess_positions)
```python
elapsed = time_module.time() - liquidation_start
if elapsed > MAX_LIQUIDATION_TIME:
    logger.warning(f"⏰ Liquidation timeout after {elapsed:.1f}s - pausing to avoid Railway kill")
    logger.warning(f"   Closed {successfully_closed}/{excess_count} positions this cycle")
    logger.warning(f"   Remaining will be handled in next run")
    break  # Stop cleanly, don't hang
```

## Expected Behavior Now

### Startup Sequence (Should complete in <5 seconds):
1. ✅ Container starts
2. ✅ Bot initializes (defers liquidation)
3. ✅ Main loop starts immediately
4. ✅ Railway sees healthy container
5. ✅ First trading cycle runs liquidation with 20s timeout

### Position Liquidation (Safe from Railway kill):
- ✅ Liquidates positions with timeout protection
- ✅ If timeout reached, pauses and retries next cycle
- ✅ Bot stays responsive
- ✅ No hanging or blocking

## Testing

Bot should now:
1. ✅ Start container successfully
2. ✅ Initialize without hanging
3. ✅ Begin trading loop immediately
4. ✅ Liquidate excess positions in first cycle (with timeout)
5. ✅ Continue running without crashes

## Files Changed
- `bot/trading_strategy.py`: 
  - Line 1806-1820: Added timeout_seconds parameter
  - Line 2166: Changed timeout to 20s for startup liquidation
  - Line 2218: Changed timeout to 10s for mid-cycle liquidation
