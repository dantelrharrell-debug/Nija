# Forced Position Cleanup - User Guide

## Overview

The Forced Position Cleanup system addresses critical issues with position fragmentation and dust accumulation by providing:

1. **Aggressive Dust Cleanup** - Automatically closes ALL positions < $1 USD
2. **Retroactive Position Cap Enforcement** - Prunes excess positions to stay under hard cap
3. **Multi-Account Support** - Works across platform and user accounts
4. **Per-User Position Caps** - Enforces 8-position limit **per user** across all their brokers (not per broker)

## Problem Statement

### Issues Addressed

**1. Hard Position Cap Not Enforced Retroactively**
- Previous implementation only blocked NEW positions when at cap
- Existing positions (adopted from legacy holdings) were not subject to cap
- Result: Users had 50+ positions despite 8-position cap

**2. Position Cap Not Enforced Per User**
- **CRITICAL FIX**: Position caps were enforced per broker, not per user
- If a user had 2 brokers with 5 positions each, they had 10 total (exceeds cap)
- Each broker was under cap individually, but user total exceeded limit
- **NEW BEHAVIOR**: Positions counted across ALL user's brokers, cap enforced per user

**3. Extreme Position Fragmentation**
- Many positions worth only pennies ($0.04 - $0.50)
- Trading fees and spreads eat all potential profit
- Capital locked in worthless dust positions

**4. Platform Position Count Mismatch**
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
- **Per-User Position Cap Enforcement** - Counts positions across ALL user's brokers

**Ranking Criteria for Cap Enforcement:**
1. Lowest USD value (minimize capital impact)
2. Worst P&L (cut losers first)
3. Oldest age (if available)

**Per-User Behavior:**
- Each user's positions are aggregated across ALL their brokers
- Example: User with Coinbase (5 positions) + Kraken (4 positions) = 9 total
- Cap enforced at user level: 9 positions triggers cleanup to reach 8
- Cleanup closes smallest/weakest positions first across all brokers
- Platform positions counted separately from user positions

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

# NEW: Cancel open orders during cleanup
python3 run_forced_cleanup.py --include-open-orders

# NEW: Preview with open order cancellation
python3 run_forced_cleanup.py --dry-run --include-open-orders

# NEW: Nuclear mode (startup-only cleanup with open order cancellation)
python3 run_forced_cleanup.py --include-open-orders --startup-only

# NEW: Selective cancellation (only if USD value < $1)
python3 run_forced_cleanup.py --cancel-if "usd_value<1.0"

# NEW: Selective cancellation (only for positions ranked for pruning)
python3 run_forced_cleanup.py --cancel-if "rank>max_positions"

# NEW: Combined selective conditions
python3 run_forced_cleanup.py --cancel-if "usd_value<1.0,rank>max_positions"
```

## Open Order Cancellation Modes

### Conservative Mode (Default)
By default, forced cleanup will **NOT** cancel open orders. Positions with open orders are skipped.

**Use when:** You want to preserve all active trading orders.

### Option A: Nuclear Mode (Startup-Only)
Cancel all open orders below thresholds **only on startup**.

**Configuration:**
```bash
# Via command line
python3 run_forced_cleanup.py --include-open-orders --startup-only

# Via environment variables
FORCED_CLEANUP_CANCEL_OPEN_ORDERS=true
FORCED_CLEANUP_STARTUP_ONLY=true
```

**Behavior:**
- Cancels dust + cap-excess orders on first run
- One-time normalization
- Safe afterward (reverts to conservative mode)

**Use when:** You need to clean up legacy positions once, then preserve orders.

### Option B: Selective Mode (Best Practice)
Only cancel open orders if specific conditions are met.

**Configuration:**
```bash
# Via command line
python3 run_forced_cleanup.py --cancel-if "usd_value<1.0,rank>max_positions"

# Via environment variable
FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF=usd_value<1.0,rank>max_positions
```

**Available Conditions:**
- `usd_value<X`: Cancel if position USD value is less than X
- `rank>max_positions`: Cancel if position is ranked for cap pruning

**Use when:** You want fine-grained control over which open orders get cancelled.

### Option C: Always Cancel
Cancel open orders for all positions being cleaned up.

**Configuration:**
```bash
# Via command line
python3 run_forced_cleanup.py --include-open-orders

# Via environment variable
FORCED_CLEANUP_CANCEL_OPEN_ORDERS=true
```

**Use when:** You want aggressive cleanup without preserving any orders.

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

### Scenario 3: Cleanup with Open Orders (Nuclear Mode)

**Problem:** User has 59 positions with many open orders, needs one-time cleanup

**Solution:**
```bash
# Step 1: Preview what would be cancelled
python3 run_forced_cleanup.py --dry-run --include-open-orders

# Output shows:
# [DUST][OPEN_ORDER][WOULD_CANCEL] Order xxx on SHIB-USD
# [DUST][OPEN_ORDER][WOULD_CANCEL] Order yyy on DOGE-USD
# [CAP][OPEN_ORDER][WOULD_CANCEL] Order zzz on ATOM-USD

# Step 2: Execute nuclear cleanup (startup-only)
python3 run_forced_cleanup.py --include-open-orders --startup-only

# Result:
# - Open orders cancelled for dust positions
# - Open orders cancelled for cap-excess positions
# - 59 positions → 8 positions
# - Future cleanups preserve open orders
```

### Scenario 4: Selective Open Order Cancellation

**Problem:** Cancel open orders only for tiny positions (< $1 USD)

**Solution:**
```bash
# Selective mode - only cancel if USD value < $1
python3 run_forced_cleanup.py --cancel-if "usd_value<1.0"

# This will:
# - Cancel orders for positions < $1
# - Preserve orders for larger positions
# - Still close positions per normal cleanup rules
```

### Scenario 5: Automated Cleanup via Bot

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

### Step 2: Open Order Cancellation (Optional)
```
If open order cancellation enabled:
  For each position marked for cleanup:
    Check if should cancel (based on mode):
      - Nuclear: Yes if startup
      - Selective: Yes if conditions match
      - Always: Yes
    If yes:
      Get open orders for symbol
      Cancel each order
      Log: [OPEN_ORDER][CANCELLED]
```

### Step 3: Dust Execution
```
For each dust position:
  Cancel open orders (if enabled)
  Log profit status transition (PENDING → CONFIRMED)
  Execute market sell
  Record outcome (WIN/LOSS)
```

### Step 4: Cap Enforcement
```
Remaining_positions = All positions - Dust positions
If count(Remaining_positions) > max_positions:
  Rank by: size_usd ASC, pnl_pct ASC, age DESC
  For each excess position:
    Cancel open orders (if enabled)
    Close position
```

### Step 5: Final Reconciliation
```
Verify final position count
Log summary:
  - Initial positions
  - Dust closed
  - Cap excess closed
  - Final positions
  - Total reduction
  - Open orders cancelled (if applicable)
```

## Logging Output

### Example Cleanup Log (Without Open Order Cancellation)

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

### Example Cleanup Log (With Open Order Cancellation)

```
🧹 FORCED CLEANUP TRIGGERED: STARTUP
🔍 Scanning account: platform_coinbase
   Initial positions: 59
   Cancel Open Orders: True
   Cancellation Mode: SELECTIVE (usd_value<1.0,rank>max_positions)

🧹 Found 45 dust positions

🧹 [DUST][FORCED] SHIB-USD
   Account: platform_coinbase
   Reason: Dust position ($0.43 < $1.00)
   Size: $0.43
   P&L: -2.15%
   PROFIT_STATUS = PENDING → CONFIRMED
   OUTCOME = LOSS
   🔍 Checking for open orders...
   [OPEN_ORDER][CANCELLING] Order abc123 on SHIB-USD
   ✅ [OPEN_ORDER][CANCELLED] Order abc123
   ✅ Cancelled 1 open order(s)
   ✅ CLOSED SUCCESSFULLY

🧹 [DUST][FORCED] DOGE-USD
   Account: platform_coinbase
   Reason: Dust position ($0.87 < $1.00)
   Size: $0.87
   P&L: +1.05%
   PROFIT_STATUS = PENDING → CONFIRMED
   OUTCOME = WIN
   🔍 Checking for open orders...
   (No open orders found)
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
   🔍 Checking for open orders...
   [OPEN_ORDER][CANCELLING] Order xyz789 on ATOM-USD
   ✅ [OPEN_ORDER][CANCELLED] Order xyz789
   ✅ Cancelled 1 open order(s)
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
   Open orders cancelled: 12
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

### 5. Open Order Safety
- **Default:** Open orders are preserved (conservative mode)
- **Modes:** Nuclear (startup-only), Selective (conditional), Always
- **Logging:** All order cancellations explicitly logged
- **Dry-run:** Preview shows [WOULD_CANCEL] without executing

## Configuration

### Default Settings

```python
DUST_THRESHOLD_USD = 1.00              # Positions < $1 are dust
MAX_POSITIONS = 8                      # Hard cap on total positions
CLEANUP_INTERVAL = 20                  # Cycles between cleanups (~50 min)
DRY_RUN = False                       # Execute trades (not preview)
CANCEL_OPEN_ORDERS = False            # Conservative: preserve open orders
STARTUP_ONLY = False                  # Run periodically (not just startup)
CANCEL_CONDITIONS = None              # No selective conditions
```

### Environment Variables

**Via .env file:**
```bash
# Enable open order cancellation
FORCED_CLEANUP_CANCEL_OPEN_ORDERS=true

# Nuclear mode (startup-only)
FORCED_CLEANUP_STARTUP_ONLY=true

# Selective cancellation
FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF=usd_value<1.0,rank>max_positions
```

### Customization Options

**Via Manual Script:**
```bash
--dust <amount>                 # Custom dust threshold (USD)
--max-positions <count>         # Custom position cap
--dry-run                       # Preview mode
--yes                          # Auto-confirm
--include-open-orders          # Cancel open orders during cleanup
--startup-only                 # Nuclear mode (startup-only cancellation)
--cancel-if <conditions>       # Selective cancellation conditions
```

**Via Code (bot/trading_strategy.py):**
```python
self.forced_cleanup = ForcedPositionCleanup(
    dust_threshold_usd=1.00,          # Customize
    max_positions=8,                  # Customize
    dry_run=False,                    # Customize
    cancel_open_orders=True,          # Enable open order cancellation
    startup_only=False,               # Nuclear mode (startup-only)
    cancel_conditions="usd_value<1.0" # Selective conditions
)
```

**Recommended Production Settings:**

For best practice, use selective cancellation:
```bash
# .env configuration
FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF=usd_value<1.0,rank>max_positions

# This will:
# - Cancel orders for positions < $1 USD
# - Cancel orders for positions ranked for cap pruning
# - Preserve all other open orders
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
- **Tests:** `test_forced_cleanup.py`, `test_user_position_caps.py`

## Expected Output Format

When running cleanup, you should see per-user position aggregation:

```
👥 USER ACCOUNTS
----------------------------------------------------------------------

👤 USER: user_123
----------------------------------------------------------------------
   📊 Active Positions: 9 (across 2 broker(s))
   🧹 Found 0 dust positions
   📊 Active Positions (after dust cleanup): 9
   🔒 Position cap exceeded: 9/8

🧹 [CAP_EXCEEDED][FORCED] BTC-USD
   Account: user_user_123_coinbase
   Reason: Position cap exceeded (9/8)
   Size: $5.00
   P&L: +2.50%
   PROFIT_STATUS = PENDING → CONFIRMED
   OUTCOME = WIN
   ✅ CLOSED SUCCESSFULLY

   👤 USER user_123 SUMMARY:
      Initial: 9 positions
      Dust closed: 0
      Cap excess closed: 1
      Final: 8 positions
```

**Key Points:**
- Position count shows TOTAL across all user's brokers
- Cap enforcement happens at USER level (not per broker)
- Each user limited to 8 positions total
- Platform accounts counted separately from user accounts

## Version History

**v2.0 (Feb 2026)**
- **BREAKING CHANGE:** Per-user position cap enforcement
- Positions counted across all user's brokers (not per broker)
- Enhanced logging with per-user aggregation
- Clear user-level summaries in output

**v1.0 (Feb 2026)**
- Initial implementation
- Dust cleanup
- Retroactive cap enforcement
- Multi-account support
- Automatic integration
- Manual execution script
