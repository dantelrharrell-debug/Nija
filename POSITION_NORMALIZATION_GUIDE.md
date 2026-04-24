# Position Normalization Feature

## Overview

Position normalization is a critical feature that enforces account hygiene by:
1. **Keeping only the largest positions** by USD value
2. **Permanently blacklisting sub-$1 dust positions**
3. **Preventing new entries when over position cap**

This reduces position counts from 59→5 or 54→5, making logs readable and risk predictable.

## Problem Statement

Before normalization:
- Users accumulate 50+ tiny positions from failed trades, partial fills, or old holdings
- Logs become unreadable with dozens of sub-$1 positions
- Risk calculations are unpredictable
- Position cap enforcement is ineffective

After normalization:
- Only the 5-8 largest positions remain active
- Sub-$1 positions are permanently ignored
- Logs are clean and readable
- Risk is predictable and manageable

## Architecture

### Components

#### 1. DustBlacklist (`bot/dust_blacklist.py`)
- **Purpose**: Permanent storage for sub-$1 position exclusions
- **Storage**: JSON file at `data/dust_blacklist.json`
- **Thread-safe**: Uses threading.Lock for concurrent access
- **Persistence**: Survives bot restarts

**Key Methods:**
```python
blacklist = get_dust_blacklist()

# Add symbol to blacklist
blacklist.add_to_blacklist("DUST-USD", usd_value=0.50, reason="dust position")

# Check if blacklisted
if blacklist.is_blacklisted("DUST-USD"):
    # Skip this position

# Get statistics
stats = blacklist.get_stats()  # {'count': 10, 'threshold_usd': 1.0, 'symbols': [...]}
```

#### 2. PositionCapEnforcer (`bot/position_cap_enforcer.py`)
- **Purpose**: Enforce maximum position count by auto-liquidating excess
- **Strategy**: Keep LARGEST positions, liquidate SMALLEST
- **Integration**: Automatically blacklists positions < $1 during fetching

**Key Changes:**
- Reversed ranking logic: Now keeps largest instead of smallest
- Integrated dust blacklist filtering
- Enhanced logging to show which positions are kept vs. liquidated

**Usage:**
```python
from position_cap_enforcer import PositionCapEnforcer

enforcer = PositionCapEnforcer(max_positions=5, broker=broker)
success, result = enforcer.enforce_cap()

# Result includes:
# - current_count: Number of positions before enforcement
# - max_allowed: Position cap limit
# - excess: Number of positions over cap
# - sold: Number successfully liquidated
# - status: 'compliant', 'enforced', or 'partial'
```

#### 3. TradingStrategy Integration (`bot/trading_strategy.py`)
- **Purpose**: Filter blacklisted positions before cap checks
- **Implementation**: Added blacklist filtering after unsellable position filtering
- **Effect**: Blacklisted positions don't count toward position limits

**Position Filtering Flow:**
1. Fetch positions from broker(s)
2. Filter out unsellable positions (timeout-based)
3. **Filter out blacklisted positions (permanent)**
4. Check against position cap
5. Block new entries if at/over cap

## Usage Examples

### Example 1: Basic Position Normalization

```python
# Scenario: User has 59 positions, need to normalize to 5

from bot.position_cap_enforcer import PositionCapEnforcer
from bot.dust_blacklist import get_dust_blacklist

# Initialize
enforcer = PositionCapEnforcer(max_positions=5)
blacklist = get_dust_blacklist()

# Run enforcement
success, result = enforcer.enforce_cap()

# Result:
# - 29 positions blacklisted (< $1 USD)
# - 25 positions liquidated (smallest of remaining 30)
# - 5 largest positions kept
# Final: 59 → 5 positions
```

### Example 2: Check Blacklist Status

```python
from bot.dust_blacklist import get_dust_blacklist

blacklist = get_dust_blacklist()

# Get all blacklisted symbols
symbols = blacklist.get_blacklisted_symbols()
print(f"Blacklisted: {symbols}")

# Get statistics
stats = blacklist.get_stats()
print(f"Total blacklisted: {stats['count']}")
print(f"Threshold: ${stats['threshold_usd']:.2f}")
```

### Example 3: Manual Blacklist Management

```python
from bot.dust_blacklist import get_dust_blacklist

blacklist = get_dust_blacklist()

# Manually add a symbol
blacklist.add_to_blacklist("JUNK-USD", usd_value=0.30, reason="manual exclusion")

# Remove a symbol (if needed)
blacklist.remove_from_blacklist("JUNK-USD")

# Clear entire blacklist (emergency reset)
blacklist.clear_blacklist()
```

## Configuration

### Position Cap
Set in environment variable or defaults to 8:
```bash
MAX_POSITIONS_ALLOWED=5
```

### Dust Threshold
Hardcoded in `dust_blacklist.py`:
```python
DUST_THRESHOLD_USD = 1.00  # Positions below this are blacklisted
```

### Data Directory
Default is `./data/` but can be overridden:
```python
blacklist = DustBlacklist(data_dir="/custom/path")
```

## Operational Notes

### When Normalization Runs

1. **On every trading cycle** in `TradingStrategy.run()`
   - Position cap is checked
   - Blacklist filtering is applied
   - Excess positions are liquidated if over cap

2. **On position fetch** in `PositionCapEnforcer.get_current_positions()`
   - Sub-$1 positions are detected
   - Automatically added to permanent blacklist
   - Excluded from position count

### Entry Blocking

When positions ≥ max_allowed:
- New entries are **blocked**
- Only exit/management operations allowed
- Status logged: "ENTRY BLOCKED: Position cap reached"
- Continues until positions < max_allowed

### Blacklist Persistence

- **File**: `data/dust_blacklist.json`
- **Format**: JSON with timestamp and symbol list
- **Atomic writes**: Uses temp file + rename for safety
- **Thread-safe**: Locked during read/write operations
- **Survives restarts**: Loaded on bot startup

### Expected Log Output

```
🔍 ENFORCE: Checking position cap (max=5)...
   Current positions: 30 (after blacklist filtering)
   🗑️  Filtered 29 blacklisted position(s) from count (permanent dust exclusion)
🚨 OVER CAP by 25 positions! Auto-liquidating...
   Strategy: KEEP 5 largest, SELL 25 smallest

Ranked 30 positions for liquidation:
  📊 KEEPING largest positions, selling smallest:
  1. DUST1-USD: $0.50 (LIQUIDATE)
  ...
  25. MED5-USD: $20.00 (LIQUIDATE)
  
  📌 Positions to KEEP (largest 5):
  1. BTC-USD: $1000.00 (KEEP)
  2. ETH-USD: $900.00 (KEEP)
  3. SOL-USD: $800.00 (KEEP)
  4. ADA-USD: $700.00 (KEEP)
  5. XRP-USD: $600.00 (KEEP)

Selling position 1/25...
✅ SOLD DUST1! Order placed.
...

ENFORCER SUMMARY: Sold 25/25 excess positions
```

## Testing

Run the comprehensive test suite:
```bash
python test_position_normalization.py
```

**Tests include:**
1. Dust blacklist persistence and functionality
2. Position ranking (keeping largest, selling smallest)
3. Position filtering with blacklist integration
4. Complete normalization workflow (59→5 positions)

## Security Considerations

### CodeQL Scan Results
✅ **No security vulnerabilities found**

### Thread Safety
- All blacklist operations use `threading.Lock`
- Atomic file writes prevent corruption
- Safe for concurrent access

### Error Handling
- Graceful fallbacks if dust_blacklist import fails
- Handles missing/corrupted blacklist files
- Logs all errors with context

## Troubleshooting

### Blacklist not working
1. Check if `data/dust_blacklist.json` exists
2. Verify file permissions (must be writable)
3. Check logs for import errors
4. Try manually initializing: `get_dust_blacklist()`

### Positions not being liquidated
1. Verify position cap is set correctly
2. Check broker connection status
3. Review broker API errors in logs
4. Ensure positions are not in unsellable timeout

### Too many positions blacklisted
1. Review blacklist file: `cat data/dust_blacklist.json`
2. Check threshold is correct (should be $1.00)
3. Manually remove symbols if needed
4. Clear entire blacklist: `blacklist.clear_blacklist()`

## Migration Notes

### Upgrading from Previous Versions

1. **Automatic migration**: Dust positions will be detected and blacklisted on first run
2. **No action required**: System auto-discovers sub-$1 positions
3. **Blacklist builds over time**: As positions are detected, they're added permanently

### Reverting Changes

If you need to disable normalization:
1. Remove dust blacklist integration from trading_strategy.py
2. Revert position_cap_enforcer.py ranking changes
3. Delete `data/dust_blacklist.json`

## Future Enhancements

Potential improvements:
- Configurable dust threshold per user tier
- Automatic cleanup of stale blacklist entries
- UI dashboard for blacklist management
- Metrics on positions normalized over time

## Summary

Position normalization ensures:
✅ Only largest positions remain active
✅ Sub-$1 dust positions are permanently excluded
✅ Logs are clean and readable
✅ Risk is predictable and manageable
✅ Entry blocking enforced when over cap

**Result**: 59 positions → 5 positions, predictable risk, readable logs.
