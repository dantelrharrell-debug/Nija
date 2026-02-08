# Forced Position Cleanup - User Guide

## Overview

The Forced Position Cleanup system addresses critical issues with position fragmentation and dust accumulation by providing:

1. **Aggressive Dust Cleanup** - Automatically closes ALL positions < $1 USD
2. **Retroactive Position Cap Enforcement** - Prunes excess positions to stay under hard cap
3. **Multi-Account Support** - Works across platform and user accounts

## Problem Statement

### Issues Addressed

**1. Hard Position Cap Not Enforced Retroactively**
- Previous implementation only blocked NEW positions when at cap
- Existing positions (adopted from legacy holdings) were not subject to cap
- Result: Users had 50+ positions despite 8-position cap

**2. Extreme Position Fragmentation**
- Many positions worth only pennies ($0.04 - $0.50)
- Trading fees and spreads eat all potential profit
- Capital locked in worthless dust positions

**3. Platform Position Count Mismatch**
- Internal tracker shows different count than exchange
- Phantom positions or missed holdings
- Inconsistent exit logic

## Solution Architecture

### Components

#### 1. ForcedPositionCleanup Engine
**File:** `bot/forced_position_cleanup.py`

**Features:**
- Identifies dust positions (< $1 USD by default)
- Ranks positions for cap enforcement (smallest → largest)
- Executes market sells with proper logging
- Supports dry-run mode for testing
- Multi-account aware

**Ranking Criteria for Cap Enforcement:**
1. Lowest USD value (minimize capital impact)
2. Worst P&L (cut losers first)
3. Oldest age (if available)

#### 2. Automatic Integration
**File:** `bot/trading_strategy.py`

**Integration Points:**
- **Startup:** Runs forced cleanup on bot initialization
- **Periodic:** Runs every 20 cycles (~50 minutes)
- **Multi-Account:** Processes all platform and user accounts

#### 3. Manual Execution Script
**File:** `run_forced_cleanup.py`

**Usage:**
```bash
# Preview what would be closed (safe)
python3 run_forced_cleanup.py --dry-run

# Execute cleanup with default settings
python3 run_forced_cleanup.py

# Custom dust threshold and position cap
python3 run_forced_cleanup.py --dust 0.50 --max-positions 5

# Skip confirmation prompt
python3 run_forced_cleanup.py --yes
```

## Usage Examples

### Scenario 1: Emergency Cleanup

**Problem:** User has 59 positions, most are dust

**Solution:**
```bash
# Step 1: Preview cleanup
python3 run_forced_cleanup.py --dry-run

# Output shows:
# - 45 dust positions (< $1 USD)
# - 6 cap excess positions (over 8 limit)
# - Final: 8 positions remaining

# Step 2: Execute cleanup
python3 run_forced_cleanup.py

# Result:
# - 59 positions → 8 positions
# - Capital consolidated from fragments
# - All dust eliminated
```

### Scenario 2: Custom Cleanup Parameters

**Problem:** User wants stricter limits (5 positions, $2 dust threshold)

**Solution:**
```bash
python3 run_forced_cleanup.py --max-positions 5 --dust 2.00
```

### Scenario 3: Automated Cleanup via Bot

**Setup:** The bot automatically runs forced cleanup:

1. **At Startup:** Cleans up legacy positions immediately
2. **Periodically:** Every 20 cycles (~50 minutes)
3. **Multi-Account:** All platform and user accounts

**No manual intervention required** - cleanup runs automatically in background.

## Cleanup Process Flow

### Step 1: Dust Identification
```
For each position:
  If size_usd < dust_threshold:
    Mark as DUST
    Priority: HIGH
    Log: [DUST][FORCED]
```

### Step 2: Dust Execution
```
For each dust position:
  Log profit status transition (PENDING → CONFIRMED)
  Execute market sell
  Record outcome (WIN/LOSS)
```

### Step 3: Cap Enforcement
```
Remaining_positions = All positions - Dust positions
If count(Remaining_positions) > max_positions:
  Rank by: size_usd ASC, pnl_pct ASC, age DESC
  Close excess positions until count <= cap
```

### Step 4: Final Reconciliation
```
Verify final position count
Log summary:
  - Initial positions
  - Dust closed
  - Cap excess closed
  - Final positions
  - Total reduction
```

## Logging Output

### Example Cleanup Log

```
🧹 FORCED CLEANUP TRIGGERED: STARTUP
🔍 Scanning account: platform_coinbase
   Initial positions: 59

🧹 Found 45 dust positions

🧹 [DUST][FORCED] SHIB-USD
   Account: platform_coinbase
   Reason: Dust position ($0.43 < $1.00)
   Size: $0.43
   P&L: -2.15%
   PROFIT_STATUS = PENDING → CONFIRMED
   OUTCOME = LOSS
   ✅ CLOSED SUCCESSFULLY

... (repeated for each dust position)

🔒 Position cap exceeded: 14/8

🧹 [CAP_EXCEEDED][FORCED] ATOM-USD
   Account: platform_coinbase
   Reason: Position cap exceeded (14/8)
   Size: $3.20
   P&L: +0.50%
   PROFIT_STATUS = PENDING → CONFIRMED
   OUTCOME = WIN
   ✅ CLOSED SUCCESSFULLY

... (repeated for each excess position)

🧹 CLEANUP COMPLETE: platform_coinbase
   Successful: 51
   Failed: 0

📊 FINAL SUMMARY
   Accounts processed: 1
   Initial total positions: 59
   Dust positions closed: 45
   Cap excess closed: 6
   Final total positions: 8
   Total reduced by: 51
```

## Safety Features

### 1. Dry Run Mode
- **Default:** Available in manual script
- **Purpose:** Preview cleanup without executing trades
- **Usage:** `--dry-run` flag

### 2. Confirmation Prompts
- **Default:** Required for manual execution
- **Override:** `--yes` flag for automation
- **Safety:** Prevents accidental execution

### 3. Profit Status Tracking
- **Feature:** Explicit logging of PENDING → CONFIRMED transitions
- **Purpose:** Ensure forced exits are counted as wins/losses
- **Prevents:** Positions stuck in "pending" state

### 4. Multi-Account Isolation
- **Feature:** Each account processed independently
- **Safety:** Errors in one account don't block others
- **Logging:** Clear account identification in all logs

## Configuration

### Default Settings

```python
DUST_THRESHOLD_USD = 1.00      # Positions < $1 are dust
MAX_POSITIONS = 8              # Hard cap on total positions
CLEANUP_INTERVAL = 20          # Cycles between cleanups (~50 min)
DRY_RUN = False               # Execute trades (not preview)
```

### Customization Options

**Via Manual Script:**
```bash
--dust <amount>          # Custom dust threshold (USD)
--max-positions <count>  # Custom position cap
--dry-run               # Preview mode
--yes                   # Auto-confirm
```

**Via Code (bot/trading_strategy.py):**
```python
self.forced_cleanup = ForcedPositionCleanup(
    dust_threshold_usd=1.00,    # Customize
    max_positions=8,            # Customize
    dry_run=False              # Customize
)
```

## Integration with Existing Systems

### DustPreventionEngine
- **Purpose:** Continuous position health scoring
- **Cleanup:** Complements forced cleanup (health-based vs. threshold-based)
- **Usage:** Both systems can coexist

### PositionCapEnforcer
- **Purpose:** Block new entries when at cap
- **Cleanup:** Forced cleanup handles retroactive enforcement
- **Relationship:** Enforcer = preventive, Cleanup = corrective

### PositionManager
- **Purpose:** Persistent position tracking
- **Cleanup:** Forced cleanup validates against live broker data
- **Sync:** Cleanup updates position manager state

## Troubleshooting

### Issue: "No positions found"
**Cause:** Broker connection failed or no positions exist
**Solution:** Check broker credentials, verify account has positions

### Issue: "Cleanup failed to close position"
**Cause:** Insufficient balance, API rate limit, invalid symbol
**Solution:** Check logs for specific error, retry after delay

### Issue: "Position count still high after cleanup"
**Cause:** Close orders failed or positions below minimum size
**Solution:** Review logs for failed closes, manually verify on exchange

### Issue: "DRY RUN shows nothing"
**Cause:** No positions meet criteria (all > dust threshold, under cap)
**Solution:** This is normal if positions are already clean

## Performance Impact

### Expected Reductions

**Typical Case:**
- **Before:** 50-60 positions (many dust)
- **After:** 5-8 positions (consolidated)
- **Reduction:** 85-90%

**Extreme Case (Issue Example):**
- **Before:** 59 positions, balance $70
- **Dust:** ~45 positions < $1
- **After Dust Cleanup:** 14 positions
- **After Cap Enforcement:** 8 positions
- **Final Reduction:** 86%

### Benefits

1. **Capital Efficiency:** Eliminates locked capital in dust
2. **Fee Reduction:** Fewer positions = fewer ongoing fees
3. **Focus:** Trade quality positions only
4. **Clarity:** Easier to monitor and manage portfolio

## Best Practices

1. **Run Dry-Run First:** Always preview before executing
2. **Monitor Logs:** Review cleanup results carefully
3. **Check Exchange:** Verify final state on exchange UI
4. **Schedule Regularly:** Let automated cleanup handle maintenance
5. **Adjust Thresholds:** Tune dust/cap based on account size

## Support & Documentation

- **Implementation:** `bot/forced_position_cleanup.py`
- **Integration:** `bot/trading_strategy.py` (search "FORCED CLEANUP")
- **Manual Tool:** `run_forced_cleanup.py`
- **Tests:** `test_forced_cleanup.py`

## Version History

**v1.0 (Feb 2026)**
- Initial implementation
- Dust cleanup
- Retroactive cap enforcement
- Multi-account support
- Automatic integration
- Manual execution script
