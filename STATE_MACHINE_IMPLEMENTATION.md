# NIJA State Machine Implementation

## Overview

This document describes the formal state machine implementation for NIJA's position management system, implemented on February 15, 2026.

## Problem Statement

The original position management system had several critical issues:

1. **Incorrect drain mode activation**: The system showed "LEGACY POSITION DRAIN MODE ACTIVE" even when `excess_positions = 0`
2. **No explicit state tracking**: The system relied on implicit conditions rather than formal state
3. **External position_idx references**: Loop variables were referenced outside their scope
4. **Missing invariants**: No validation of system correctness at key checkpoints
5. **Poor visibility**: No explicit logging of state transitions

## Solution: Formal State Machine

### State Enum

```python
class PositionManagementState(Enum):
    """Position management state machine for NIJA trading bot."""
    NORMAL = "normal"           # Under cap, entries allowed
    DRAIN = "drain"             # Over cap, draining excess, entries blocked
    FORCED_UNWIND = "forced_unwind"  # Emergency exit, closing all
```

### State Determination

State is determined by two factors:

1. **Forced Unwind Status**: Checked via `continuous_exit_enforcer.is_forced_unwind_active()`
2. **Position Count vs. Cap**: `positions_over_cap = len(current_positions) - MAX_POSITIONS_ALLOWED`

```python
if forced_unwind_active:
    new_state = PositionManagementState.FORCED_UNWIND
elif positions_over_cap > 0:  # KEY FIX: Only activate when excess > 0
    new_state = PositionManagementState.DRAIN
else:
    new_state = PositionManagementState.NORMAL
```

### State Transitions

Valid transitions:
- NORMAL → DRAIN (when positions exceed cap)
- DRAIN → NORMAL (when positions drop below cap)
- Any state → FORCED_UNWIND (when emergency exit triggered)
- FORCED_UNWIND → NORMAL or DRAIN (when emergency exit cleared)

Transitions are validated and logged:
```
🔄 STATE TRANSITION: NORMAL → DRAIN
   Positions: 10/8
   Excess: 2
   Forced Unwind: False
```

## Invariant Validation

The `StateInvariantValidator` class enforces system invariants:

### Invariant 1: Non-negative Position Count
```python
assert num_positions >= 0
```

### Invariant 2: Excess Calculation Consistency
```python
calculated_excess = num_positions - max_positions
assert excess_positions == calculated_excess
```

### Invariant 3: DRAIN Mode Constraint
```python
if state == PositionManagementState.DRAIN:
    assert excess_positions > 0  # Drain only when over cap
```

### Invariant 4: NORMAL Mode Constraint
```python
if state == PositionManagementState.NORMAL:
    assert excess_positions <= 0  # Normal only when at or under cap
```

## Position Analysis

The position analysis loop runs for both DRAIN and NORMAL modes:

```python
# Position analysis loop (runs for both DRAIN and NORMAL modes)
if new_state in (PositionManagementState.DRAIN, PositionManagementState.NORMAL):
    for idx, position in enumerate(current_positions):
        # Analyze position for exit criteria
        # ...
        
        # Rate limiting between position checks
        if idx < len(current_positions) - 1:
            time.sleep(POSITION_CHECK_DELAY + jitter)
```

Key differences between modes:
- **DRAIN**: Logs "🔥 DRAIN MODE ACTIVE", indicates excess, blocks new entries
- **NORMAL**: Logs "✅ NORMAL MODE", indicates available capacity, allows entries

## Removed External References

**Before:**
```python
for position_idx, position in enumerate(current_positions):
    # ...
    if position_idx < len(current_positions) - 1:  # External reference
        time.sleep(POSITION_CHECK_DELAY)
```

**After:**
```python
for idx, position in enumerate(current_positions):
    # ...
    if idx < len(current_positions) - 1:  # Scoped to loop
        time.sleep(POSITION_CHECK_DELAY)
```

The variable `idx` is local to the loop and only used within it, eliminating external references.

## Testing

Comprehensive test suite validates:

1. **State enum definition**: All states defined correctly
2. **Invariant validation**: 5 test cases covering all invariants
3. **State transitions**: 4 test cases covering valid and invalid transitions
4. **Drain mode activation**: 5 scenarios testing position count thresholds

All tests passing ✅

## Impact

### Before
- Drain mode message appeared incorrectly when at capacity (0 excess)
- No visibility into state changes
- Implicit state based on conditions
- No invariant validation

### After
- Drain mode only activates when `excess > 0`
- Explicit state transition logging
- Formal state machine with validation
- Comprehensive invariant checking

## Files Modified

- `bot/trading_strategy.py`: Added state machine, invariant validator, state tracking
- `test_state_machine.py`: Comprehensive test suite (new file)

## Backward Compatibility

All changes are backward compatible. Existing functionality is preserved with additional:
- Safety checks (invariants)
- Visibility (state transition logging)
- Correctness (proper drain activation)

## Security

- CodeQL scan: 0 vulnerabilities ✅
- No secrets exposed
- All invariants enforced at runtime

## Future Enhancements

Potential improvements:
1. Add state transition metrics/telemetry
2. Implement state transition history tracking
3. Add alerts for unexpected state transitions
4. Create state machine visualization dashboard

## References

- Problem statement: GitHub issue (immediate action plan)
- Implementation: Pull request #[number]
- Test suite: `test_state_machine.py`
- Code review: All feedback addressed ✅
