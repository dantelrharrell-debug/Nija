# NIJA Analytics Quick Reference

## Command Line

```bash
# Generate basic report
python generate_analytics_report.py

# Detailed report with session stats
python generate_analytics_report.py --detailed

# Export trades to CSV
python generate_analytics_report.py --export-csv

# Custom time window (48 hours)
python generate_analytics_report.py --capital-hours 48

# Custom data directory
python generate_analytics_report.py --data-dir /path/to/data
```

## Integration Snippets

### Market Scan Timing

```python
from bot.analytics_integration import MarketScanTimer

with MarketScanTimer(total_markets=732, batch_size=30, batch_number=1) as timer:
    for symbol in markets:
        timer.add_market_scanned()
        if signal: timer.add_signal()
        if trade: timer.add_trade()
```

### Capital Utilization

```python
from bot.analytics_integration import log_capital_utilization

log_capital_utilization(total_capital, positions, broker)
```

### Trade Entry Tracking

```python
from bot.analytics_integration import infer_entry_reason, infer_signal_type

conditions = {'rsi_9': 25, 'rsi_14': 28}
entry_reason = infer_entry_reason(conditions)
signal_type = infer_signal_type(conditions)
```

### Trade Exit Tracking

```python
from bot.analytics_integration import map_exit_reason_to_enum

exit_reason = map_exit_reason_to_enum("Profit target hit (25% position)")
```

## Programmatic Access

```python
from bot.trade_analytics import get_analytics

analytics = get_analytics()

# PnL attribution
pnl_attr = analytics.get_pnl_attribution()
dual_rsi_pnl = pnl_attr['by_signal']['dual_rsi']

# Reason codes
reason_codes = analytics.get_reason_code_summary()
total_trades = reason_codes['total_trades']

# Scan performance
scan_perf = analytics.get_scan_performance()
est_time = scan_perf['estimated_full_scan_time']

# Capital history
recent = analytics.get_recent_capital_utilization(hours=24)

# Full report
report = analytics.generate_analytics_report()
print(report)
```

## Entry Reasons (11 total)

- `rsi_9_oversold` - RSI_9 < 30
- `rsi_14_oversold` - RSI_14 < 30
- `dual_rsi_oversold` - Both RSI < 30
- `rsi_divergence` - Divergence detected
- `tradingview_buy_signal` - TradingView buy
- `tradingview_sell_signal` - TradingView sell
- `market_readiness_passed` - Quality gate passed
- `strong_momentum` - Strong momentum
- `manual_entry` - Manual trade
- `heartbeat_trade` - Connectivity test
- `unknown` - Fallback

## Exit Reasons (17 total)

**Profit Targets:**
- `profit_target_1/2/3` - Partial exits (25% each)
- `full_profit_target` - 100% exit
- `trailing_stop_hit` - Trailing stop

**Stop Losses:**
- `stop_loss_hit` - Stop loss
- `time_based_stop` - Max hold time (24h+)
- `losing_trade_exit` - Aggressive loss cut (15min)

**RSI Exits:**
- `rsi_overbought` - RSI > 55
- `rsi_oversold_exit` - RSI < 45

**Risk Management:**
- `daily_loss_limit` - Daily loss limit
- `position_limit_enforcement` - Position cap
- `kill_switch` - Emergency kill switch
- `liquidate_all` - Emergency liquidation

**Position Management:**
- `dust_position` - Position < $1
- `zombie_position` - Stuck position
- `adoption_exit` - Adopted/legacy position

**Manual:**
- `manual_exit` - User-initiated
- `unknown` - Fallback

## Signal Types (for PnL Attribution)

- `rsi_9_only` - RSI_9 signal only
- `rsi_14_only` - RSI_14 signal only
- `dual_rsi` - Both RSI indicators
- `tradingview` - TradingView webhook
- `heartbeat` - Heartbeat trade
- `manual` - Manual trade
- `unknown` - Fallback

## Data Files

```
data/analytics/
├── pnl_attribution.json         # PnL by signal/strategy
├── market_scans.jsonl           # Scan history (append-only)
├── capital_utilization.jsonl    # Capital snapshots (append-only)
└── reason_codes_summary.json    # Reason code statistics
```

## Key Metrics

**Market Scan Efficiency:**
- Target: < 150s to scan 732 markets
- Monitor: `estimated_full_scan_time`

**Capital Utilization:**
- Ideal: 60-80% utilization
- Monitor: `utilization_pct`

**Trade Quality:**
- Good: High profit target exits
- Bad: High stop loss exits

## Common Patterns

### Scan Too Slow?
```python
scan_perf = analytics.get_scan_performance()
if scan_perf['estimated_full_scan_time'] > 150:
    print(f"Slow scans: {scan_perf['avg_scan_time_seconds']:.1f}s")
    print(f"Rate limits: {scan_perf['total_rate_limit_delays_ms']}ms")
    # Consider: reducing batch size, increasing delays
```

### Capital Underutilized?
```python
capital = analytics.get_recent_capital_utilization(hours=1)
if capital:
    util_pct = capital[-1]['utilization_pct']
    if util_pct < 60:
        print(f"Low utilization: {util_pct:.1f}%")
        # Consider: larger position sizes, more positions
```

### Poor Win Rate?
```python
reason_codes = analytics.get_reason_code_summary()
exits = reason_codes['exit_reasons']
stop_loss_pct = exits.get('stop_loss_hit', {}).get('percentage', 0)
if stop_loss_pct > 30:
    print(f"High stop loss rate: {stop_loss_pct:.1f}%")
    # Consider: better entry criteria, wider stops
```

## Testing

```bash
# Run analytics tests
cd /home/runner/work/Nija/Nija
python3 -c "from bot.trade_analytics import get_analytics; print('✅ Import OK')"
python3 -c "from bot.analytics_integration import MarketScanTimer; print('✅ Integration OK')"
python3 generate_analytics_report.py --help
```

## Files Reference

| File | Purpose | Lines |
|------|---------|-------|
| `bot/trade_analytics.py` | Core analytics engine | ~900 |
| `bot/analytics_integration.py` | Integration helpers | ~380 |
| `generate_analytics_report.py` | CLI report tool | ~180 |
| `ANALYTICS_SYSTEM_GUIDE.md` | Full documentation | ~500 |

## Performance Tips

1. **Use context managers** - Automatic logging on exit
2. **Log capital periodically** - Not every cycle (too verbose)
3. **Batch reason code updates** - Update after trade completion
4. **Archive old logs** - Keep JSONL files manageable
5. **Export to CSV regularly** - For deeper analysis in Excel/Pandas
