# NIJA Audit Logging System

## Overview

The **Audit Logging System** provides tamper-evident, compliance-grade logging for all critical trading operations. Every significant event is logged with cryptographic checksums to ensure data integrity and provide a complete audit trail.

## Key Features

### 1. Tamper-Evident Logs
- SHA-256 checksums on every log entry
- Immutable append-only log files
- Verification methods to detect tampering

### 2. Structured Format
- Standardized JSON schema
- Machine-readable and queryable
- Human-readable when pretty-printed

### 3. Complete Audit Trail
- Trade lifecycle (entry → exits → final P&L)
- Position size validations
- Profit proven milestone checks
- Risk control decisions
- System events

### 4. Regulatory Compliance
- Meets audit requirements for financial systems
- Provides complete reconstruction of all trading decisions
- Timestamped with millisecond precision

## Log Format

### Standard Log Entry

Every audit log entry follows this schema:

```json
{
  "event_id": "AE-20260206145823123456-000042",
  "event_type": "trade_entry",
  "timestamp": "2026-02-06T14:58:23.123456Z",
  "user_id": "platform",
  "account_id": "coinbase_main",
  "broker": "coinbase",
  "trade_id": "TRD-BTC-20260206-001",
  "symbol": "BTC-USD",
  "event_data": {
    "side": "long",
    "entry_price": 50000.0,
    "stop_loss": 49500.0,
    "take_profit": 51000.0,
    "strategy": "apex_v71",
    "rsi_9": 35.2,
    "rsi_14": 38.5
  },
  "validation_result": true,
  "validation_reason": null,
  "amount_usd": null,
  "position_size_usd": 100.0,
  "account_balance_usd": 1000.0,
  "checksum": "a7f3c2d1e4b5a6c8f9d0e1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2"
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | string | Yes | Unique event identifier (format: AE-{timestamp}-{counter}) |
| `event_type` | string | Yes | Type of event (see Event Types below) |
| `timestamp` | string | Yes | ISO 8601 timestamp with milliseconds + Z suffix |
| `user_id` | string | Yes | User identifier |
| `account_id` | string | No | Account identifier (broker-specific) |
| `broker` | string | No | Broker name (coinbase, kraken, etc.) |
| `trade_id` | string | No | Trade identifier (for trade events) |
| `symbol` | string | No | Trading symbol (for trade/position events) |
| `event_data` | object | No | Event-specific data (flexible schema) |
| `validation_result` | boolean | No | Result of validation (for validation events) |
| `validation_reason` | string | No | Reason for validation failure |
| `amount_usd` | number | No | USD amount involved |
| `position_size_usd` | number | No | Position size in USD |
| `account_balance_usd` | number | No | Account balance at event time |
| `checksum` | string | Yes | SHA-256 checksum of entry (hex-encoded) |

## Event Types

### Trade Lifecycle Events

| Event Type | Description | When Logged |
|------------|-------------|-------------|
| `trade_entry` | Trade entry executed | When position is opened |
| `trade_partial_exit` | Partial position exit | When taking partial profits |
| `trade_full_exit` | Full position exit | When position is completely closed |
| `trade_stop_loss` | Stop loss hit | When stop loss is triggered |
| `trade_take_profit` | Take profit hit | When take profit is triggered |

### Position & Risk Events

| Event Type | Description | When Logged |
|------------|-------------|-------------|
| `position_size_validation` | Position size approved | Before every trade entry |
| `position_size_rejected` | Position size rejected | When exceeding limits |
| `position_limit_enforced` | Hard limit enforced | When hitting absolute caps |
| `max_position_override_blocked` | Override attempt blocked | When trying to bypass limits |

### Profit Proven Events

| Event Type | Description | When Logged |
|------------|-------------|-------------|
| `profit_proven_check` | Status check performed | Regular intervals + after trades |
| `profit_proven_achieved` | Criteria met ✅ | When all criteria pass |
| `profit_proven_failed` | Criteria not met ❌ | When time window expires without meeting criteria |

### Risk Control Events

| Event Type | Description | When Logged |
|------------|-------------|-------------|
| `kill_switch_triggered` | Kill switch activated | When trading is halted |
| `kill_switch_reset` | Kill switch reset | When trading is re-enabled |
| `daily_loss_limit_hit` | Daily loss limit reached | When daily losses exceed limit |
| `daily_trade_limit_hit` | Daily trade limit reached | When daily trades exceed limit |

### System Events

| Event Type | Description | When Logged |
|------------|-------------|-------------|
| `trading_session_start` | Bot started | On startup |
| `trading_session_end` | Bot stopped | On clean shutdown |
| `emergency_shutdown` | Emergency stop | On critical errors |

## Usage Guide

### 1. Initialize Audit Logger

```python
from bot.trading_audit_logger import get_audit_logger

# Get global instance
audit_logger = get_audit_logger()

# Or specify custom log directory
from bot.trading_audit_logger import AuditLogger
audit_logger = AuditLogger(log_dir="./custom_audit_logs")
```

### 2. Log Trade Entry

```python
# When entering a trade
entry = audit_logger.log_trade_entry(
    user_id="platform",
    trade_id="TRD-BTC-001",
    symbol="BTC-USD",
    side="long",
    entry_price=50000.0,
    position_size_usd=100.0,
    stop_loss=49500.0,
    take_profit=51000.0,
    account_balance_usd=1000.0,
    broker="coinbase",
    # Additional custom data
    strategy="apex_v71",
    rsi_9=35.2,
    rsi_14=38.5,
    entry_score=8.5
)

# Entry is automatically checksummed and written to disk
print(f"Logged: {entry.event_id}")
```

### 3. Log Trade Exit

```python
# When exiting a trade (full or partial)
exit_entry = audit_logger.log_trade_exit(
    user_id="platform",
    trade_id="TRD-BTC-001",
    symbol="BTC-USD",
    exit_type="take_profit",  # or 'stop_loss', 'partial', 'full'
    exit_price=51000.0,
    exit_size_pct=1.0,  # 100% = full exit
    gross_pnl_usd=20.0,
    fees_usd=0.40,
    net_pnl_usd=19.60,
    account_balance_usd=1019.60,
    exit_reason="Take profit level 1 hit",
    # Additional custom data
    hold_time_minutes=45,
    max_favorable_excursion=1.5,
    max_adverse_excursion=-0.3
)
```

### 4. Log Position Validation

```python
# When validating position size
validation_entry = audit_logger.log_position_validation(
    user_id="platform",
    symbol="ETH-USD",
    requested_size_usd=150.0,
    account_balance_usd=1000.0,
    is_approved=False,
    rejection_reason="Position too large: $150.00 (maximum $100.00, 10%)",
    enforced_limit="MAX_POSITION_PCT",
    # Additional data
    max_allowed_pct=10.0,
    requested_pct=15.0
)
```

### 5. Log Profit Proven Check

```python
# When checking profit proven status
from bot.profit_proven_rule import get_profit_proven_tracker

tracker = get_profit_proven_tracker()
is_proven, status, metrics = tracker.check_profit_proven()

# Log the check
check_entry = audit_logger.log_profit_proven_check(
    user_id="platform",
    is_proven=is_proven,
    metrics=metrics,
    criteria=tracker.criteria.to_dict()
)
```

### 6. Query Audit Logs

```python
from bot.trading_audit_logger import AuditEventType
from datetime import datetime, timedelta

# Query specific event type
trade_entries = audit_logger.query_events(
    event_type=AuditEventType.TRADE_ENTRY,
    user_id="platform",
    limit=100
)

# Query by trade ID
trade_lifecycle = audit_logger.query_events(
    trade_id="TRD-BTC-001",
    limit=50
)

# Query recent events
since_time = datetime.now() - timedelta(hours=24)
recent_events = audit_logger.query_events(
    since=since_time,
    limit=1000
)

# Process results
for event in trade_entries:
    print(f"{event.timestamp}: {event.event_type} - {event.symbol}")
    print(f"  Checksum valid: {event.verify_checksum()}")
```

### 7. Verify Checksum

```python
# Verify log entry integrity
entry = audit_logger.query_events(trade_id="TRD-BTC-001")[0]

if entry.verify_checksum():
    print("✅ Log entry is valid and untampered")
else:
    print("🚨 WARNING: Log entry may have been tampered with!")
```

## Log File Organization

Logs are automatically organized into separate files by category:

```
data/audit_logs/
├── trades.jsonl              # All trade lifecycle events
├── positions.jsonl           # Position validation events
├── profit_proven.jsonl       # Profit proven milestone events
├── risk_control.jsonl        # Kill switch and limit events
└── system.jsonl              # System startup/shutdown events
```

Each file uses JSONL format (JSON Lines):
- One complete JSON object per line
- Easy to process with streaming tools
- Efficient for large log files

## Integration Examples

### Automatic Trade Logging

Integrate with execution engine:

```python
class ExecutionEngine:
    def __init__(self):
        self.audit_logger = get_audit_logger()
    
    def execute_entry(self, signal):
        # ... execute trade ...
        
        # Log to audit
        self.audit_logger.log_trade_entry(
            user_id=signal.user_id,
            trade_id=trade.id,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=fill_price,
            position_size_usd=position_size,
            stop_loss=stop_price,
            take_profit=target_price,
            account_balance_usd=self.get_balance(),
            broker=self.broker_name,
            **signal.metadata  # Include signal metadata
        )
    
    def execute_exit(self, trade, exit_reason):
        # ... execute exit ...
        
        # Log to audit
        self.audit_logger.log_trade_exit(
            user_id=trade.user_id,
            trade_id=trade.id,
            symbol=trade.symbol,
            exit_type=self._determine_exit_type(exit_reason),
            exit_price=fill_price,
            exit_size_pct=exit_pct,
            gross_pnl_usd=gross_pnl,
            fees_usd=total_fees,
            net_pnl_usd=net_pnl,
            account_balance_usd=self.get_balance(),
            exit_reason=exit_reason
        )
```

### Daily Audit Report

Generate daily audit reports:

```python
def generate_daily_audit_report(date: datetime):
    """Generate comprehensive audit report for a specific date"""
    audit_logger = get_audit_logger()
    
    # Query all events for the day
    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    events = audit_logger.query_events(since=start_of_day, limit=10000)
    
    # Categorize events
    trades_entered = [e for e in events if e.event_type == "trade_entry"]
    trades_exited = [e for e in events if e.event_type in ["trade_full_exit", "trade_stop_loss", "trade_take_profit"]]
    validations_failed = [e for e in events if e.event_type == "position_size_rejected"]
    
    # Generate report
    report = {
        'date': date.isoformat(),
        'summary': {
            'total_events': len(events),
            'trades_entered': len(trades_entered),
            'trades_exited': len(trades_exited),
            'validations_failed': len(validations_failed),
        },
        'integrity_check': {
            'total_entries': len(events),
            'valid_checksums': sum(1 for e in events if e.verify_checksum()),
            'invalid_checksums': sum(1 for e in events if not e.verify_checksum()),
        },
        'events': [e.to_dict() for e in events]
    }
    
    return report
```

## Best Practices

### 1. Always Log Critical Events

```python
# ✅ DO: Log all trade entries and exits
audit_logger.log_trade_entry(...)
audit_logger.log_trade_exit(...)

# ✅ DO: Log position validations (especially rejections)
audit_logger.log_position_validation(...)

# ❌ DON'T: Skip logging "minor" trades - all trades matter for audit
```

### 2. Include Relevant Context

```python
# ✅ DO: Include strategy metadata
audit_logger.log_trade_entry(
    ...,
    strategy="apex_v71",
    rsi_9=35.2,
    rsi_14=38.5,
    trend_strength=72.0,
    market_regime="trending"
)

# ❌ DON'T: Log minimal information
audit_logger.log_trade_entry(
    user_id="platform",
    trade_id="TRD-001",
    symbol="BTC-USD",
    # Missing critical context!
)
```

### 3. Verify Checksums Regularly

```python
def verify_audit_integrity():
    """Verify integrity of audit logs"""
    audit_logger = get_audit_logger()
    events = audit_logger.query_events(limit=1000)
    
    invalid_count = 0
    for event in events:
        if not event.verify_checksum():
            invalid_count += 1
            logger.error(f"Invalid checksum: {event.event_id}")
    
    if invalid_count > 0:
        logger.critical(f"🚨 {invalid_count} log entries have invalid checksums!")
    else:
        logger.info("✅ All audit log checksums valid")
    
    return invalid_count == 0
```

### 4. Archive Old Logs

```python
import shutil
from pathlib import Path

def archive_old_logs(days_old=30):
    """Archive audit logs older than specified days"""
    log_dir = Path("./data/audit_logs")
    archive_dir = Path("./data/audit_logs/archive")
    archive_dir.mkdir(exist_ok=True)
    
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    # Process each log file
    for log_file in log_dir.glob("*.jsonl"):
        if should_archive(log_file, cutoff_date):
            archive_path = archive_dir / f"{log_file.stem}_{cutoff_date.strftime('%Y%m')}.jsonl.gz"
            compress_and_move(log_file, archive_path)
```

## Compliance & Auditing

### Regulatory Requirements

The audit logging system helps meet common regulatory requirements:

1. **Complete Trade Reconstruction**: Every trade can be reconstructed from entry to exit
2. **Timestamp Accuracy**: Millisecond precision on all events
3. **Tamper Evidence**: SHA-256 checksums detect any modifications
4. **Retention**: Logs are append-only and can be archived
5. **Queryability**: Structured format allows efficient querying

### Audit Checklist

When preparing for an audit:

- ✅ Verify all checksums are valid
- ✅ Ensure no gaps in event sequences
- ✅ Confirm timestamps are monotonically increasing (within same log file)
- ✅ Validate all trades have corresponding entries and exits
- ✅ Check position validations match actual trades
- ✅ Export profit proven milestone logs
- ✅ Generate summary reports by date range

## Performance Considerations

### Write Performance

- Logs are written synchronously (blocking)
- Each write is protected by a thread lock
- Typical write time: < 1ms per event
- Recommend logging after critical operations, not before

### Query Performance

- Log files use JSONL format for streaming reads
- No indexing (sequential scan)
- Query performance: ~10,000 entries/second
- For high-volume systems, consider external log aggregation (e.g., ELK stack)

### Storage Requirements

Typical storage usage:
- Trade entry: ~500 bytes
- Trade exit: ~600 bytes
- Position validation: ~400 bytes
- Profit proven check: ~1,000 bytes

For 1,000 trades/day: ~1.5 MB/day or ~45 MB/month

## Troubleshooting

### Problem: Logs not being written

```python
# Check log directory exists and is writable
from pathlib import Path
log_dir = Path("./data/audit_logs")
print(f"Directory exists: {log_dir.exists()}")
print(f"Is writable: {os.access(log_dir, os.W_OK)}")
```

### Problem: Invalid checksums

```python
# Checksums will be invalid if entry is modified after creation
# Always verify checksums on read, never modify entries
```

### Problem: Missing events

```python
# Events are only logged if audit logger is called
# Check that integration code actually calls logging methods
```

## See Also

- [PROFIT_PROVEN_RULE.md](PROFIT_PROVEN_RULE.md) - Profit proven validation system
- [HARD_CONTROLS.md](HARD_CONTROLS.md) - Position limits and risk controls
- [SECURITY.md](SECURITY.md) - Overall security architecture
