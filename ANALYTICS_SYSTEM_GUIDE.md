# NIJA Trading Analytics System

## Overview

The NIJA Trading Analytics System provides comprehensive monitoring and reporting for trading operations across four key areas:

1. **PnL Attribution** - Track profit/loss by strategy and signal type
2. **Trade Outcome Reason Codes** - Understand why trades entered and exited
3. **Market Scan Timing Metrics** - Verify 732 markets are scanned efficiently
4. **Capital Utilization Reports** - Monitor idle vs active capital deployment

## Architecture

### Core Modules

```
bot/
├── trade_analytics.py          # Core analytics engine
├── analytics_integration.py    # Integration helpers
└── [existing modules]

generate_analytics_report.py    # CLI report generator

data/
└── analytics/                  # Analytics data files
    ├── pnl_attribution.json    # PnL by signal/strategy
    ├── market_scans.jsonl      # Market scan history
    ├── capital_utilization.jsonl # Capital snapshots
    └── reason_codes_summary.json # Reason code stats
```

### Data Structures

#### TradeRecord (Enhanced)
```python
@dataclass
class TradeRecord:
    # Core fields
    symbol: str
    entry_price: float
    exit_price: float
    # ... existing fields ...
    
    # NEW: Analytics fields
    entry_reason: str          # EntryReason enum value
    exit_reason: str           # ExitReason enum value
    entry_signal_type: str     # SignalType enum value
    strategy_name: str         # e.g., "apex_v71"
    rsi_9_value: float
    rsi_14_value: float
    broker: str
```

#### MarketScanMetrics
```python
@dataclass
class MarketScanMetrics:
    duration_seconds: float
    total_markets_available: int
    markets_scanned: int
    avg_time_per_market_ms: float
    total_api_calls: int
    total_rate_limit_delays_ms: float
    signals_generated: int
    trades_executed: int
```

#### CapitalUtilization
```python
@dataclass
class CapitalUtilization:
    total_capital_usd: float
    capital_in_positions_usd: float
    idle_capital_usd: float
    utilization_pct: float
    num_positions: int
    avg_position_size_usd: float
    largest_position_symbol: str
    unrealized_pnl_usd: float
```

## Usage

### 1. Generate Analytics Reports

#### Basic Report
```bash
python generate_analytics_report.py
```

#### Detailed Report with Session Stats
```bash
python generate_analytics_report.py --detailed
```

#### Export Trade History to CSV
```bash
python generate_analytics_report.py --export-csv
```

#### Custom Time Window
```bash
python generate_analytics_report.py --capital-hours 48
```

### 2. Integration in Trading Code

#### Market Scan Timing

Use the `MarketScanTimer` context manager to automatically track scan performance:

```python
from bot.analytics_integration import MarketScanTimer

# In your market scanning loop
with MarketScanTimer(total_markets=732, batch_size=30, batch_number=1) as timer:
    for symbol in markets_to_scan:
        # Scan market
        timer.add_market_scanned()
        
        # If signal generated
        if signal_detected:
            timer.add_signal()
        
        # If trade executed
        if trade_executed:
            timer.add_trade()
```

The timer will automatically:
- Track scan duration
- Calculate avg time per market
- Log metrics to analytics system
- Display summary in logs

#### Capital Utilization Tracking

```python
from bot.analytics_integration import log_capital_utilization

# After fetching positions and balance
positions = broker.get_positions()
total_capital = broker.get_total_capital()

# Log utilization
log_capital_utilization(total_capital, positions, broker)
```

This will log:
- Total capital and allocation
- Utilization percentage
- Position count and sizes
- Unrealized P&L

#### Trade Outcome Recording

```python
from bot.analytics_integration import infer_entry_reason, infer_signal_type

# When entering a trade
conditions = {
    'rsi_9': 25,
    'rsi_14': 28,
    'rsi_9_oversold_threshold': 30,
    'rsi_14_oversold_threshold': 30
}

entry_reason = infer_entry_reason(conditions)
signal_type = infer_signal_type(conditions)

# Store with trade record
trade_record.entry_reason = entry_reason
trade_record.entry_signal_type = signal_type
trade_record.strategy_name = "apex_v71"
```

```python
from bot.analytics_integration import map_exit_reason_to_enum

# When exiting a trade
exit_reason_str = "Profit target hit (25% position)"
exit_reason = map_exit_reason_to_enum(exit_reason_str)

trade_record.exit_reason = exit_reason
```

### 3. Programmatic Access

```python
from bot.trade_analytics import get_analytics

# Get singleton analytics instance
analytics = get_analytics()

# Get PnL attribution
pnl_attr = analytics.get_pnl_attribution()
print(f"Dual RSI P&L: ${pnl_attr['by_signal']['dual_rsi']:.2f}")

# Get reason code summary
reason_codes = analytics.get_reason_code_summary()
print(f"Total trades: {reason_codes['total_trades']}")

# Get scan performance
scan_perf = analytics.get_scan_performance()
print(f"Avg markets/scan: {scan_perf['avg_markets_per_scan']:.1f}")
estimated_time = scan_perf['estimated_full_scan_time']
print(f"Est. time for 732 markets: {estimated_time:.0f}s")

# Get capital utilization history
recent_capital = analytics.get_recent_capital_utilization(hours=24)
for snapshot in recent_capital[-5:]:
    print(f"{snapshot['timestamp']}: {snapshot['utilization_pct']:.1f}% utilized")

# Generate comprehensive report
report = analytics.generate_analytics_report()
print(report)
```

## Reason Code Reference

### Entry Reasons

| Code | Description | Trigger Condition |
|------|-------------|-------------------|
| `rsi_9_oversold` | RSI_9 oversold | RSI_9 < threshold (typically 30) |
| `rsi_14_oversold` | RSI_14 oversold | RSI_14 < threshold (typically 30) |
| `dual_rsi_oversold` | Both RSI oversold | Both RSI_9 and RSI_14 < threshold |
| `rsi_divergence` | RSI divergence | Bullish/bearish divergence detected |
| `tradingview_buy_signal` | TradingView buy | TradingView webhook buy signal |
| `tradingview_sell_signal` | TradingView sell | TradingView webhook sell signal |
| `market_readiness_passed` | Market quality OK | Passed market readiness gate |
| `strong_momentum` | Strong momentum | Strong price momentum detected |
| `manual_entry` | Manual trade | User-initiated trade |
| `heartbeat_trade` | Connectivity test | Heartbeat trade for API testing |

### Exit Reasons

| Code | Description | Trigger Condition |
|------|-------------|-------------------|
| `profit_target_1` | First profit target | +25% position at target 1 |
| `profit_target_2` | Second profit target | +25% position at target 2 |
| `profit_target_3` | Third profit target | +25% position at target 3 |
| `full_profit_target` | Final profit target | 100% position exit at target |
| `trailing_stop_hit` | Trailing stop | Trailing stop triggered |
| `stop_loss_hit` | Stop loss | Stop loss price reached |
| `time_based_stop` | Max hold time | Position held too long (24h+) |
| `losing_trade_exit` | Aggressive loss cut | Losing trade exit (15min rule) |
| `rsi_overbought` | RSI overbought | RSI > overbought threshold (55) |
| `rsi_oversold_exit` | RSI oversold exit | RSI < oversold threshold (45) |
| `daily_loss_limit` | Daily loss limit | Daily loss limit reached |
| `position_limit_enforcement` | Position cap | Position cap enforcement |
| `kill_switch` | Kill switch | Emergency kill switch activated |
| `liquidate_all` | Emergency liquidation | Emergency liquidation mode |
| `dust_position` | Dust cleanup | Position too small (< $1) |
| `zombie_position` | Stuck position | Zombie position cleanup |
| `adoption_exit` | Adopted position | Exiting adopted/legacy position |

### Signal Types (for PnL Attribution)

| Signal Type | Description |
|-------------|-------------|
| `rsi_9_only` | RSI_9 signal only |
| `rsi_14_only` | RSI_14 signal only |
| `dual_rsi` | Both RSI indicators |
| `tradingview` | TradingView webhook |
| `heartbeat` | Heartbeat trade |
| `manual` | Manual trade |

## Analytics Report Format

```
================================================================================
NIJA TRADING ANALYTICS REPORT
================================================================================
Generated: 2026-02-07T11:13:54.772290

1. PnL ATTRIBUTION BY SIGNAL TYPE
--------------------------------------------------------------------------------
   dual_rsi             $   1,234.56 (45.2%)
   rsi_9_only           $     678.90 (24.8%)
   tradingview          $     456.78 (16.7%)
   rsi_14_only          $     321.45 (11.8%)
   heartbeat            $      43.21 (1.6%)
   TOTAL                $   2,734.90

   PnL ATTRIBUTION BY STRATEGY
--------------------------------------------------------------------------------
   apex_v71             $   2,734.90

2. TRADE OUTCOME REASON CODES
--------------------------------------------------------------------------------
   Entry Reasons (Top 10):
      dual_rsi_oversold                    42 trades (48.3%)
      rsi_9_oversold                       23 trades (26.4%)
      tradingview_buy_signal               15 trades (17.2%)
      rsi_14_oversold                       7 trades (8.0%)

   Exit Reasons (Top 10):
      profit_target_1                      28 trades (32.2%)
      trailing_stop_hit                    19 trades (21.8%)
      rsi_overbought                       15 trades (17.2%)
      time_based_stop                      12 trades (13.8%)
      stop_loss_hit                         8 trades (9.2%)
      dust_position                         5 trades (5.7%)

3. MARKET SCAN PERFORMANCE
--------------------------------------------------------------------------------
   Total Scan Cycles: 125
   Total Markets Scanned: 3,750
   Avg Markets/Scan: 30.0
   Avg Scan Time: 45.50s
   Min Scan Time: 38.20s
   Max Scan Time: 58.70s
   Est. Time for 732 Markets: 1,110s (18.5m)
   ⚠️  Need 8 cycles to scan all 732 markets (18.5m total)

4. CAPITAL UTILIZATION (Latest)
--------------------------------------------------------------------------------
   Total Capital: $10,000.00
   In Positions:  $6,500.00 (65.0%)
   Idle Capital:  $3,500.00
   Number of Positions: 5
   Avg Position Size: $1,300.00
   Largest Position: BTC-USD ($2,000.00)
   Unrealized P&L: $+125.50

================================================================================
```

## Performance Insights

### Market Scan Efficiency

The analytics system helps answer:
- **Are we scanning 732 markets efficiently?**
  - Check `Est. Time for 732 Markets` in scan performance
  - Target: < 150s (2.5 minutes) for single-cycle scan
  - If higher, markets are scanned across multiple cycles

- **What's causing slow scans?**
  - Check `total_rate_limit_delays_ms` for API throttling
  - Check `avg_time_per_market_ms` for per-market overhead
  - Review `total_api_calls` for unnecessary calls

### Capital Efficiency

- **Capital Utilization %**: Ideal range 60-80%
  - < 60%: Too conservative, missing opportunities
  - > 80%: High risk, limited buffer for opportunities
  
- **Position Count**: Monitor against position cap
  - Track trend over time
  - Correlate with utilization %

### Strategy Performance

- **PnL by Signal Type**: Identify best-performing signals
  - Focus capital on high-performing signal types
  - Reduce allocation to underperforming signals
  
- **Entry/Exit Reason Analysis**: Optimize entry and exit logic
  - High profit target hits = good entry timing
  - High stop loss hits = poor entry selection
  - High time-based stops = positions not moving

## Best Practices

1. **Regular Monitoring**
   ```bash
   # Daily report
   python generate_analytics_report.py --detailed
   
   # Weekly CSV export for deeper analysis
   python generate_analytics_report.py --export-csv
   ```

2. **Integration Points**
   - Add `MarketScanTimer` to all market scanning loops
   - Log capital utilization after each balance update
   - Record reason codes for all trade entries/exits

3. **Data Retention**
   - Analytics logs use JSONL (append-only) format
   - Consider archiving old logs monthly
   - Keep at least 90 days for trend analysis

4. **Performance Tuning**
   - Monitor scan metrics to optimize batch sizes
   - Use capital utilization to adjust position sizing
   - Review reason codes to refine strategy parameters

## Troubleshooting

### No Data in Reports

Check data directory exists and has write permissions:
```bash
ls -la data/analytics/
```

Verify analytics is being called:
```python
from bot.trade_analytics import get_analytics
analytics = get_analytics()
print(f"Scan cycles: {analytics.total_scan_cycles}")
```

### Incorrect Reason Codes

Verify conditions dict passed to inference functions:
```python
from bot.analytics_integration import infer_entry_reason

# Must include all relevant fields
conditions = {
    'rsi_9': 25,
    'rsi_14': 28,
    'rsi_9_oversold_threshold': 30,
    'rsi_14_oversold_threshold': 30
}
reason = infer_entry_reason(conditions)
assert reason == 'dual_rsi_oversold'
```

### Missing Metrics

Ensure integration helpers are used:
```python
# Use context manager for automatic logging
with MarketScanTimer(...) as timer:
    # ... scan code ...
    pass  # Metrics logged on exit
```

## Future Enhancements

Potential additions to the analytics system:

1. **Real-time Dashboard**
   - Web interface for live analytics
   - Charts and visualizations
   - Alert system for anomalies

2. **Advanced Metrics**
   - Sharpe ratio by signal type
   - Win rate by entry reason
   - Average hold time by exit reason

3. **Machine Learning Integration**
   - Predict best signal types for market conditions
   - Optimize batch sizes based on scan metrics
   - Dynamic capital allocation based on utilization trends

4. **Multi-Broker Analytics**
   - Compare performance across brokers
   - Broker-specific reason code analysis
   - Cross-broker capital utilization

## Support

For questions or issues with the analytics system:
1. Check this documentation
2. Review test examples in `bot/analytics_integration.py`
3. Run tests to verify functionality
4. Check logs in `data/analytics/` directory
