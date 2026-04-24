# 🧯 FORCE_EXIT_ALL Switch - Design Specification

## Overview

**FORCE_EXIT_ALL** is a global emergency switch that immediately exits ALL positions across ALL accounts and ALL exchanges with enhanced safety, logging, and control features.

## Design Philosophy

**Differences from LIQUIDATE_ALL_NOW.conf:**

| Feature | LIQUIDATE_ALL_NOW.conf | FORCE_EXIT_ALL (New) |
|---------|------------------------|----------------------|
| Activation | File creation | JSON config file with options |
| Scope | Active broker only | ALL brokers, ALL accounts |
| Logging | Basic | Detailed with pre/post snapshots |
| Verification | None | Built-in verification & retry |
| Reporting | Log messages only | JSON report + email alert |
| Rollback | None | Option to prevent new entries after |
| Dry-run | No | Yes, with simulation mode |

## Activation Mechanism

### File Format: `FORCE_EXIT_ALL.json`

Location: Repository root (`/home/runner/work/Nija/Nija/FORCE_EXIT_ALL.json`)

```json
{
  "enabled": true,
  "reason": "Market crash - protecting capital",
  "initiated_by": "user_email@example.com",
  "initiated_at": "2026-02-04T18:00:00Z",
  "options": {
    "scope": "all",
    "dry_run": false,
    "block_new_entries_after": true,
    "notification_email": "user@example.com",
    "max_retries": 3,
    "verify_completion": true
  },
  "targets": {
    "platforms": ["PLATFORM_KRAKEN", "PLATFORM_COINBASE"],
    "users": ["USER_john_doe_KRAKEN", "USER_jane_smith_COINBASE"]
  }
}
```

### Configuration Options

**enabled** (required): `true` to activate, `false` to disable
- Controls whether the switch is active
- Safe to set to `false` mid-execution to abort

**reason** (required): Free text explaining why force exit was triggered
- Logged in all reports
- Helps with post-mortem analysis

**initiated_by** (required): User/system identifier
- Audit trail for who triggered the switch
- Email address or system identifier

**initiated_at** (required): ISO timestamp
- When the switch was activated
- Used to prevent stale config from re-triggering

**scope** (optional, default: "all"):
- `"all"`: Exit ALL positions on ALL accounts and ALL brokers
- `"platform"`: Exit only platform account positions
- `"users"`: Exit only user account positions  
- `"specific"`: Exit only accounts listed in `targets`

**dry_run** (optional, default: `false`):
- `true`: Simulate exits without placing real orders
- `false`: Execute real market sell orders
- Perfect for testing before actual emergency

**block_new_entries_after** (optional, default: `true`):
- `true`: Create `STOP_ALL_ENTRIES.conf` after force exit completes
- `false`: Allow new entries after exit
- Recommended `true` to prevent immediate re-entry

**notification_email** (optional):
- Email address to send completion report
- Requires email service configured
- Falls back to log-only if email unavailable

**max_retries** (optional, default: `3`):
- Number of retry attempts for failed sells
- Prevents infinite loops
- Each retry has 2-second delay

**verify_completion** (optional, default: `true`):
- `true`: Query exchange after exit to verify 0 positions
- `false`: Trust order execution without verification
- Recommended `true` for safety

**targets** (optional):
- Specific accounts to target when `scope="specific"`
- Format: `{"platforms": [...], "users": [...]}`
- Ignored if `scope` is not `"specific"`

## Implementation

### Location
**File**: `bot/force_exit_manager.py` (new file)  
**Integration**: Called from `independent_broker_trader.py` at start of each trading cycle

### Core Components

#### 1. ForceExitManager Class

```python
class ForceExitManager:
    """
    Manages FORCE_EXIT_ALL emergency switch.
    
    Responsibilities:
    - Detect and parse FORCE_EXIT_ALL.json
    - Coordinate exit across all accounts/brokers
    - Verify exit completion
    - Generate detailed reports
    - Handle cleanup and post-exit actions
    """
    
    def __init__(self, config_file: str = "FORCE_EXIT_ALL.json"):
        self.config_file = config_file
        self.execution_log = []
        self.start_time = None
        self.end_time = None
        
    def check_and_execute(self, all_brokers: dict) -> dict:
        """
        Check if force exit is triggered and execute if needed.
        
        Returns detailed execution report.
        """
        pass
```

#### 2. Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: Detection                                           │
│ - Check if FORCE_EXIT_ALL.json exists                      │
│ - Parse and validate configuration                          │
│ - Log initiation details                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: Pre-Exit Snapshot                                   │
│ - Query all brokers for current positions                   │
│ - Record position details (symbol, size, entry, P&L)       │
│ - Calculate total capital at risk                           │
│ - Save snapshot to force_exit_snapshot_pre.json            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: Scope Determination                                 │
│ - Filter accounts based on config.scope                     │
│ - Platform only / Users only / All / Specific               │
│ - Log which accounts will be affected                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: Execute Force Exit                                  │
│                                                              │
│ For each account in scope:                                  │
│   ├─ Get all open positions                                 │
│   ├─ For each position:                                     │
│   │   ├─ Place market sell order                           │
│   │   ├─ Wait 1 second (rate limit)                        │
│   │   ├─ Log result (success/failure)                      │
│   │   └─ Retry if failed (up to max_retries)               │
│   └─ Record account completion status                       │
│                                                              │
│ Process all accounts in PARALLEL where possible             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 5: Post-Exit Verification (if enabled)                │
│ - Query all brokers again for positions                     │
│ - Verify position count = 0                                 │
│ - If positions remain, log warning + details                │
│ - Save snapshot to force_exit_snapshot_post.json           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 6: Post-Exit Actions                                   │
│ - Create STOP_ALL_ENTRIES.conf (if configured)             │
│ - Generate execution report                                 │
│ - Send notification email (if configured)                   │
│ - Archive FORCE_EXIT_ALL.json with timestamp               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 7: Cleanup & Resume                                    │
│ - Move config to archive/                                   │
│ - Clear in-memory force exit state                          │
│ - Trading resumes next cycle (with no entries if blocked)   │
└─────────────────────────────────────────────────────────────┘
```

### Thread Safety

**Challenge**: Multiple trading threads (one per account) may detect the switch simultaneously.

**Solution**: 
- First thread to detect switch acquires global lock
- Creates `FORCE_EXIT_ALL.lock` file
- Other threads detect lock and wait
- Lock holder executes exit for ALL accounts
- Lock holder removes lock file when done
- Other threads skip their exit (already done)

```python
def execute_with_lock(self):
    """Execute force exit with global lock to prevent race conditions."""
    lock_file = "FORCE_EXIT_ALL.lock"
    
    # Try to acquire lock
    if os.path.exists(lock_file):
        logger.info("Another thread is handling force exit, waiting...")
        # Wait for lock to clear
        for _ in range(30):  # Max 30 seconds
            if not os.path.exists(lock_file):
                return  # Exit already handled
            time.sleep(1)
        return
    
    # Acquire lock
    with open(lock_file, 'w') as f:
        f.write(f"Locked by PID {os.getpid()} at {datetime.now().isoformat()}")
    
    try:
        # Execute force exit
        self.execute_all()
    finally:
        # Always release lock
        if os.path.exists(lock_file):
            os.remove(lock_file)
```

## Execution Report

### Report Format: `force_exit_report_TIMESTAMP.json`

```json
{
  "execution_id": "force_exit_20260204_180000",
  "config": {
    "reason": "Market crash - protecting capital",
    "initiated_by": "user@example.com",
    "initiated_at": "2026-02-04T18:00:00Z",
    "scope": "all",
    "dry_run": false
  },
  "timing": {
    "started_at": "2026-02-04T18:00:15Z",
    "completed_at": "2026-02-04T18:00:47Z",
    "duration_seconds": 32
  },
  "pre_exit_state": {
    "total_accounts": 5,
    "total_positions": 12,
    "total_capital_deployed_usd": 15750.00,
    "accounts": [
      {
        "account_id": "PLATFORM_KRAKEN",
        "positions": 3,
        "capital_usd": 5000.00
      }
    ]
  },
  "execution_details": {
    "accounts_processed": 5,
    "positions_sold": 12,
    "positions_failed": 0,
    "total_orders_placed": 12,
    "retries_needed": 1
  },
  "post_exit_state": {
    "total_positions_remaining": 0,
    "verification_passed": true,
    "warnings": []
  },
  "position_details": [
    {
      "account_id": "PLATFORM_KRAKEN",
      "symbol": "BTCUSD",
      "quantity_sold": 0.02,
      "entry_price": 50000.00,
      "exit_price": 51200.00,
      "pnl_pct": 2.4,
      "pnl_usd": 24.00,
      "status": "success",
      "order_id": "ORDER_12345",
      "timestamp": "2026-02-04T18:00:16Z"
    }
  ],
  "summary": {
    "total_pnl_usd": 425.50,
    "total_pnl_pct": 2.7,
    "success_rate": 100.0,
    "all_positions_closed": true
  },
  "post_actions": {
    "stop_entries_created": true,
    "notification_sent": true,
    "config_archived": true
  }
}
```

## Safety Features

### 🔒 Guardrail 1: Stale Config Prevention

```python
def is_config_stale(self, config: dict, max_age_minutes: int = 10) -> bool:
    """
    Prevent accidentally re-triggering old force exit configs.
    
    Config is stale if initiated_at > max_age_minutes ago.
    """
    initiated_at = datetime.fromisoformat(config['initiated_at'])
    age = datetime.now() - initiated_at
    
    if age.total_seconds() > max_age_minutes * 60:
        logger.warning(f"Config is {age.total_seconds()/60:.1f} min old (stale)")
        return True
    
    return False
```

### 🔒 Guardrail 2: Dry-Run Mode

```python
def place_sell_order(self, broker, symbol, quantity, dry_run: bool):
    """Place sell order with dry-run support."""
    if dry_run:
        logger.info(f"[DRY-RUN] Would sell {quantity} {symbol}")
        return {
            'status': 'simulated',
            'message': 'Dry-run mode - no real order placed'
        }
    else:
        # Real order execution
        return broker.place_market_order(symbol, 'sell', quantity)
```

### 🔒 Guardrail 3: Position Verification

```python
def verify_all_closed(self, all_brokers: dict) -> tuple:
    """
    Verify all positions are actually closed.
    
    Returns:
        (success: bool, remaining_positions: list)
    """
    remaining = []
    
    for account_id, broker in all_brokers.items():
        positions = broker.get_positions()
        if positions:
            remaining.extend([
                {'account': account_id, 'symbol': p['symbol']} 
                for p in positions
            ])
    
    return (len(remaining) == 0, remaining)
```

### 🔒 Guardrail 4: Execution Timeout

```python
MAX_EXECUTION_TIME = 300  # 5 minutes

def execute_all(self):
    """Execute with timeout protection."""
    start = time.time()
    
    for account_id, broker in self.get_target_brokers():
        # Check timeout
        if time.time() - start > MAX_EXECUTION_TIME:
            logger.error("Force exit TIMEOUT - aborting remaining accounts")
            break
        
        self.process_account(account_id, broker)
```

### 🔒 Guardrail 5: Abort Switch

User can abort mid-execution by setting `enabled: false`:

```python
def should_continue(self) -> bool:
    """Check if force exit should continue (allows mid-execution abort)."""
    if not os.path.exists(self.config_file):
        logger.warning("Config file removed - aborting force exit")
        return False
    
    config = self.load_config()
    if not config.get('enabled', False):
        logger.warning("Config disabled - aborting force exit")
        return False
    
    return True
```

## Usage Examples

### Example 1: Emergency Market Crash

```json
{
  "enabled": true,
  "reason": "Bitcoin flash crash -30% - protecting all accounts",
  "initiated_by": "risk_manager@company.com",
  "initiated_at": "2026-02-04T14:30:00Z",
  "options": {
    "scope": "all",
    "dry_run": false,
    "block_new_entries_after": true,
    "notification_email": "team@company.com",
    "max_retries": 5,
    "verify_completion": true
  }
}
```

### Example 2: Dry-Run Test

```json
{
  "enabled": true,
  "reason": "Testing force exit mechanism",
  "initiated_by": "admin@company.com",
  "initiated_at": "2026-02-04T18:00:00Z",
  "options": {
    "scope": "all",
    "dry_run": true,
    "block_new_entries_after": false,
    "verify_completion": false
  }
}
```

### Example 3: User Accounts Only

```json
{
  "enabled": true,
  "reason": "User account security concern",
  "initiated_by": "security@company.com",
  "initiated_at": "2026-02-04T18:00:00Z",
  "options": {
    "scope": "users",
    "dry_run": false,
    "block_new_entries_after": true,
    "notification_email": "users@company.com"
  }
}
```

### Example 4: Specific Account

```json
{
  "enabled": true,
  "reason": "john_doe reported suspicious activity",
  "initiated_by": "support@company.com",
  "initiated_at": "2026-02-04T18:00:00Z",
  "options": {
    "scope": "specific",
    "dry_run": false,
    "block_new_entries_after": true
  },
  "targets": {
    "users": ["USER_john_doe_KRAKEN"]
  }
}
```

## Monitoring & Alerts

### Log Indicators

**Force exit detected**:
```
🧯 FORCE EXIT ALL TRIGGERED
   Reason: Market crash - protecting capital
   Initiated by: user@example.com
   Scope: all
   Dry-run: false
```

**Execution progress**:
```
📊 Force Exit Progress:
   Accounts: 3/5 processed
   Positions: 8/12 sold
   Success rate: 100%
   Elapsed: 15 seconds
```

**Completion**:
```
✅ FORCE EXIT ALL COMPLETE
   Duration: 32 seconds
   Positions closed: 12/12
   Verification: PASSED
   Report: force_exit_report_20260204_180000.json
```

### Email Alert Template

```
Subject: 🧯 FORCE EXIT ALL Executed

A force exit has been executed on your NIJA trading system.

DETAILS:
- Reason: Market crash - protecting capital
- Initiated by: user@example.com
- Time: 2026-02-04 18:00:00 UTC
- Scope: All accounts

RESULTS:
- Accounts processed: 5
- Positions closed: 12/12
- Total P&L: +$425.50 (+2.7%)
- Success rate: 100%
- Verification: PASSED

POST-ACTIONS:
- New entries blocked: YES
- All positions closed: YES

NEXT STEPS:
- Review full report: force_exit_report_20260204_180000.json
- Determine when to resume trading
- Remove STOP_ALL_ENTRIES.conf to allow new trades

This is an automated message from NIJA Force Exit Manager.
```

## Comparison with LIQUIDATE_ALL_NOW.conf

### Keep LIQUIDATE_ALL_NOW.conf?

**Recommendation**: Keep both, with clear distinction:

**LIQUIDATE_ALL_NOW.conf** (Simple):
- Quick activation (just create file)
- No configuration needed
- Current broker only
- Basic logging
- **Use when**: Need immediate exit, no time for config

**FORCE_EXIT_ALL.json** (Advanced):
- Requires JSON config (more setup)
- Full control over scope and options
- ALL brokers and accounts
- Detailed reporting and verification
- **Use when**: Want controlled, verified, documented exit

### Migration Path

1. Keep both mechanisms active
2. Document use cases for each
3. Eventually deprecate LIQUIDATE_ALL_NOW.conf if FORCE_EXIT_ALL proves superior
4. Provide migration helper: `convert_liquidate_to_force_exit.py`

## Implementation Checklist

- [ ] Create `bot/force_exit_manager.py`
- [ ] Add ForceExitManager class with all methods
- [ ] Integrate into independent_broker_trader.py
- [ ] Add thread safety (lock mechanism)
- [ ] Implement pre/post snapshots
- [ ] Add verification logic
- [ ] Create report generator
- [ ] Add email notification support
- [ ] Write comprehensive tests
- [ ] Document in user guide
- [ ] Create example configs
- [ ] Test dry-run mode
- [ ] Test multi-account scenarios
- [ ] Security scan
- [ ] Code review

## Security Considerations

✅ **No credentials in config**: Config file contains no API keys
✅ **Read-only after trigger**: Config archived, not modified
✅ **Audit trail**: Full logging of who triggered and why
✅ **Verification**: Double-checks positions actually closed
✅ **Timeout protection**: Can't run forever
✅ **Abort mechanism**: Can stop mid-execution
✅ **Stale config protection**: Won't re-trigger old configs

## Summary

FORCE_EXIT_ALL is a production-grade emergency switch that:

✅ Exits ALL positions across ALL accounts/brokers
✅ Provides granular control via JSON config
✅ Generates detailed execution reports
✅ Verifies completion
✅ Supports dry-run testing
✅ Thread-safe for multi-account environments
✅ Includes comprehensive safety features
✅ Maintains full audit trail

It's the **ultimate safety mechanism** for NIJA's unified strategy per account architecture.
