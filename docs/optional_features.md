# Optional Future Enhancements - Documentation

This document describes three optional enhancements implemented to improve the NIJA trading bot's operational efficiency and monitoring capabilities.

## Overview

These are nice-to-have features that enhance the bot's behavior but are not critical for core functionality:

1. **Minimum Notional Gate at Entry** - Prevents dust positions at source
2. **Position Score Telemetry** - Tracks position scoring decisions for strategy tuning
3. **Cleanup Metrics Dashboard** - Monitors dust removal and capital efficiency

None of these features block performance or safety - they are quality-of-life improvements.

---

## Enhancement #1: Minimum Notional Gate at Entry

### Purpose
Prevents sub-$X entries from ever opening, reducing reliance on cleanup over time.

### Philosophy
"Better to not enter than to enter dust"

### Location
- **Module**: `bot/minimum_notional_gate.py`
- **Integration**: `bot/execution_engine.py`

### Configuration

```python
from bot.minimum_notional_gate import MinimumNotionalGate, NotionalGateConfig

# Default configuration
config = NotionalGateConfig(
    enabled=True,
    min_entry_notional_usd=25.0,  # $25 minimum by default
    allow_stop_loss_bypass=True,  # Stop losses can bypass
    broker_specific_limits={
        'coinbase': 25.0,   # $25 (profitability threshold)
        'kraken': 10.0,     # $10 (lower fees)
        'binance': 10.0,    # $10 (lower fees)
        'okx': 10.0,        # $10 (lower fees)
        'alpaca': 1.0,      # $1 (stocks, no crypto fees)
    }
)

gate = MinimumNotionalGate(config)
```

### How It Works

1. Before placing an entry order, the execution engine checks the position size
2. If size < minimum notional for that broker, the entry is rejected
3. Stop loss orders can bypass the gate (configurable)
4. Rejections are logged with clear reasons

### Benefits

- ✅ Prevents dust accumulation at source
- ✅ Reduces cleanup operations needed
- ✅ Improves capital efficiency
- ✅ Broker-aware (different minimums for different fee structures)

### Example Usage

```python
# In execution_engine.py, before placing order:
if MIN_NOTIONAL_GATE_AVAILABLE:
    notional_gate = get_minimum_notional_gate()
    is_valid, reason = notional_gate.validate_entry_size(
        symbol="BTC-USD",
        size_usd=position_size,
        is_stop_loss=False,
        broker_name="coinbase"
    )
    
    if not is_valid:
        logger.warning(f"❌ Entry rejected: {reason}")
        return None
```

### Disabling

To disable the minimum notional gate:

```python
config = NotionalGateConfig(enabled=False)
gate = MinimumNotionalGate(config)
```

---

## Enhancement #2: Position Score Telemetry

### Purpose
Track why positions survive pruning to help with strategy tuning.

### Philosophy
"Data-driven position management"

### Location
- **Module**: `bot/position_score_telemetry.py`
- **Integration**: `bot/dust_prevention_engine.py`

### Data Tracked

For each position score calculation:
- ✅ Symbol and timestamp
- ✅ Health score (0-100)
- ✅ P&L percentage
- ✅ Age in hours
- ✅ Stagnation hours
- ✅ **Score breakdown** (P&L contribution, stagnation contribution, age contribution)
- ✅ Health status (excellent, good, fair, unhealthy)
- ✅ Whether position survived pruning
- ✅ Pruning reason (if applicable)

### Data Files

All telemetry is saved to JSON files in the `data/` directory:

- **`position_score_records.jsonl`** - One line per score record (append-only)
- **`position_pruning_events.jsonl`** - One line per pruning event (append-only)
- **`position_telemetry_summary.json`** - Aggregated summary (updated)

### Example Data

```json
{
  "timestamp": "2026-02-08T14:21:39.598948",
  "symbol": "BTC-USD",
  "score": 85.0,
  "pnl_pct": 0.025,
  "age_hours": 2.0,
  "stagnation_hours": 0.5,
  "pnl_contribution": 30.0,
  "stagnation_contribution": 10.0,
  "age_contribution": 5.0,
  "survived_pruning": true,
  "health_status": "excellent",
  "size_usd": 100.0
}
```

### Usage

The telemetry is automatically recorded when positions are scored in the dust prevention engine:

```python
from bot.position_score_telemetry import get_position_telemetry

telemetry = get_position_telemetry()

# Record a score
telemetry.record_position_score(
    symbol="BTC-USD",
    score=85.0,
    pnl_pct=0.025,
    age_hours=2.0,
    stagnation_hours=0.5,
    pnl_contribution=30.0,
    stagnation_contribution=10.0,
    age_contribution=5.0,
    survived_pruning=True,
    health_status="excellent",
    size_usd=100.0
)

# Record a pruning event
telemetry.record_pruning_event(
    symbol="ETH-USD",
    reason="Unhealthy position",
    cleanup_type="UNHEALTHY",
    final_score=25.0,
    final_pnl_pct=-0.015,
    size_usd=50.0,
    age_hours=12.0
)

# Generate report
report = telemetry.generate_telemetry_report()
telemetry.print_summary()
```

### Analysis Queries

You can analyze the telemetry data to:
- Find patterns in positions that survive vs get pruned
- Tune scoring thresholds
- Understand which factors matter most
- Identify optimal position holding periods

### Disabling

To disable telemetry in DustPreventionEngine:

```python
engine = DustPreventionEngine(
    max_positions=5,
    enable_telemetry=False  # Disable telemetry
)
```

---

## Enhancement #3: Cleanup Metrics Dashboard

### Purpose
Track dust removed, capital reclaimed, and position size trends over time.

### Philosophy
"Measure to improve"

### Location
- **Module**: `bot/cleanup_metrics_tracker.py`
- **Integration**: `bot/dust_prevention_engine.py`

### Metrics Tracked

**Daily Metrics:**
- Dust positions removed (count and USD value)
- Cap-exceeded removals
- Unhealthy position removals
- Stagnant position removals
- Total capital reclaimed
- Average position size
- Total P&L from cleanup operations

**Trends:**
- Position size trends (increasing/decreasing/stable)
- Cleanup frequency over time
- Capital efficiency improvements

### Data Files

All metrics are saved to the `data/` directory:

- **`cleanup_events.jsonl`** - Every cleanup event (append-only)
- **`cleanup_daily_metrics.json`** - Aggregated daily metrics
- **`cleanup_dashboard.json`** - Current dashboard data

### Example Daily Metrics

```json
{
  "2026-02-08": {
    "date": "2026-02-08",
    "dust_positions_removed": 2,
    "dust_capital_reclaimed": 1.7,
    "unhealthy_removals": 2,
    "unhealthy_capital": 90.0,
    "total_removals": 4,
    "total_capital_reclaimed": 91.7,
    "avg_position_size": 130.0,
    "total_pnl_from_cleanup": -2.28
  }
}
```

### Usage

```python
from bot.cleanup_metrics_tracker import get_cleanup_metrics_tracker

tracker = get_cleanup_metrics_tracker()

# Record a cleanup event
tracker.record_cleanup(
    symbol="BTC-USD",
    cleanup_type="DUST",
    size_usd=0.85,
    pnl_pct=-0.02,
    age_hours=24.0,
    reason="Dust position ($0.85 < $1.00)"
)

# Track position sizes for trend analysis
tracker.track_position_size(size_usd=100.0)

# Get daily metrics
today_metrics = tracker.get_daily_metrics()  # Today's metrics
last_week = tracker.get_last_n_days(7)       # Last 7 days
last_month = tracker.get_last_n_days(30)     # Last 30 days

# Get position size trend
trend = tracker.get_position_size_trend(days=30)
print(f"Trend: {trend['trend']}")  # 'increasing', 'decreasing', or 'stable'
print(f"Average Size: ${trend['avg_size']:.2f}")

# Generate and print dashboard
tracker.print_dashboard()

# Save dashboard data to file
tracker.save_dashboard_data()
```

### Dashboard Output Example

```
======================================================================
CLEANUP METRICS DASHBOARD
======================================================================

📅 TODAY (2026-02-08):
   Dust Removed: 2 positions ($1.70)
   Total Removals: 4 ($91.70)
   Cleanup P&L: $-2.28
   Avg Position Size: $130.00

📊 LAST 7 DAYS:
   Dust Removed: 2 positions
   Capital Reclaimed: $91.70
   Total Removals: 4
   Cleanup P&L: $-2.28

📈 LAST 30 DAYS:
   Dust Removed: 2 positions
   Capital Reclaimed: $91.70
   Total Removals: 4
   Cleanup P&L: $-2.28

📏 POSITION SIZE TREND (30 days):
   Average: $130.00
   Range: $75.00 - $200.00
   Trend: STABLE (+0.0%)
   Data Points: 5
======================================================================
```

### Disabling

To disable cleanup metrics in DustPreventionEngine:

```python
engine = DustPreventionEngine(
    max_positions=5,
    enable_cleanup_metrics=False  # Disable cleanup metrics
)
```

---

## Integration Summary

### DustPreventionEngine Integration

The dust prevention engine now has three optional enhancements:

```python
from bot.dust_prevention_engine import DustPreventionEngine

engine = DustPreventionEngine(
    max_positions=5,
    stagnation_hours=4.0,
    min_pnl_movement=0.002,
    auto_dust_cleanup_enabled=True,
    dust_threshold_usd=1.00,
    enable_telemetry=True,        # Enhancement #2
    enable_cleanup_metrics=True   # Enhancement #3
)
```

### ExecutionEngine Integration

The execution engine now checks minimum notional before placing orders:

```python
from bot.execution_engine import ExecutionEngine
from bot.minimum_notional_gate import NotionalGateConfig, get_minimum_notional_gate

# Initialize gate (done once at startup)
config = NotionalGateConfig(
    enabled=True,
    min_entry_notional_usd=25.0
)
gate = get_minimum_notional_gate(config)

# Engine automatically uses gate when placing orders
engine = ExecutionEngine(broker_client=broker)
result = engine.execute_entry(
    symbol="BTC-USD",
    side="long",
    position_size=30.0,  # Will pass minimum notional
    entry_price=50000.0,
    stop_loss=49000.0,
    take_profit_levels={...}
)
```

---

## Performance Impact

All three enhancements are designed with minimal performance impact:

- ✅ **Minimum Notional Gate**: Single comparison before order placement (< 1ms)
- ✅ **Position Telemetry**: Append-only file writes, non-blocking (< 5ms per record)
- ✅ **Cleanup Metrics**: Aggregation done in-memory, file writes are batched (< 10ms per cleanup)

Total overhead: **< 20ms per position lifecycle**

---

## File Locations

### Code Files
```
/bot/minimum_notional_gate.py      # Enhancement #1
/bot/position_score_telemetry.py   # Enhancement #2
/bot/cleanup_metrics_tracker.py    # Enhancement #3
```

### Data Files
```
/data/position_score_records.jsonl      # Telemetry records
/data/position_pruning_events.jsonl     # Pruning events
/data/position_telemetry_summary.json   # Telemetry summary
/data/cleanup_events.jsonl              # Cleanup events
/data/cleanup_daily_metrics.json        # Daily metrics
/data/cleanup_dashboard.json            # Dashboard data
```

---

## Future Enhancements

Possible future additions:

1. **Web Dashboard UI** - Visualize cleanup metrics and telemetry in a web interface
2. **Alerting** - Send alerts when cleanup rate exceeds thresholds
3. **Auto-tuning** - Use telemetry to automatically adjust scoring thresholds
4. **Historical Analysis** - Tools to analyze weeks/months of telemetry data
5. **Export to CSV** - Export metrics for external analysis

---

## FAQ

**Q: Do I need to enable all three enhancements?**
A: No, each enhancement is independent and can be enabled/disabled separately.

**Q: Will these enhancements affect my existing positions?**
A: No, they only affect new entries and existing position monitoring. They don't change core trading logic.

**Q: How much disk space do the data files use?**
A: Very minimal - typically < 1MB per month of trading. Files are JSONL (line-delimited) for efficient append operations.

**Q: Can I disable these features after enabling them?**
A: Yes, simply set the enabled flags to False. Existing data files will be preserved.

**Q: Are these enhancements required for the bot to work?**
A: No, these are optional quality-of-life improvements. The bot works fine without them.

---

## Support

For questions or issues related to these enhancements, please refer to:
- Main documentation: `README.md`
- Dust prevention: `DUST_PREVENTION_ENGINE.md`
- Position management: `POSITION_MANAGEMENT.md`
