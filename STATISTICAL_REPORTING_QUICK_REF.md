# NIJA Statistical Reporting - Quick Reference

## Quick Commands

### Generate Reports
```bash
# Print summary to console
python bot/statistical_reporting_module.py --summary

# Export all reports
python bot/statistical_reporting_module.py --export

# Custom output directory
python bot/statistical_reporting_module.py --export --output-dir /path/to/reports
```

### Integration Example
```bash
# Run complete integration example
python bot/institutional_grade_integration_example.py
```

## Python API

### Display Disclaimers
```python
from bot.institutional_disclaimers import print_validation_banner
print_validation_banner()
```

### Performance Tracking
```python
from bot.performance_tracking_layer import get_performance_tracking_layer

perf = get_performance_tracking_layer()
perf.set_initial_balance(10000.0)

# Record trade
perf.record_trade(
    symbol='BTC-USD',
    strategy='APEX_V71',
    side='buy',
    entry_price=45000,
    exit_price=46000,
    quantity=0.1,
    profit=100,
    fees=2
)

# Get statistics
stats = perf.get_statistics_summary()
print(f"Win Rate (Last 100): {stats['win_rate_last_100']:.2f}%")
print(f"Max Drawdown: {stats['max_drawdown_pct']:.2f}%")
print(f"Rolling Expectancy: ${stats['rolling_expectancy']:.2f}")
```

### Strategy Validation
```python
from bot.validation_layer import get_validation_layer

validation = get_validation_layer()
result = validation.validate_strategy(
    strategy_name="APEX_V71",
    historical_trades=backtest_data,
    validation_period_days=90
)

print(f"Win Rate: {result.win_rate:.2f}%")
print(f"Profit Factor: {result.profit_factor:.2f}")
```

### Marketing Reports
```python
from bot.marketing_layer import get_marketing_layer

marketing = get_marketing_layer()

# Export reports
marketing.export_investor_report(format='json')
marketing.export_investor_report(format='txt')
marketing.export_equity_curve_csv()

# Get summary
summary = marketing.get_summary_for_marketing()
print(summary)
```

### Statistical Reporting
```python
from bot.statistical_reporting_module import get_statistical_reporting_module

module = get_statistical_reporting_module()

# Print summary
module.print_summary()

# Generate report
report = module.generate_comprehensive_report()

# Export all
exports = module.export_all_reports()
```

## Key Statistics

### Win Rate (Last 100 Trades)
Percentage of profitable trades in the most recent 100 trades.

### Max Drawdown
Maximum peak-to-trough decline in account value (percentage).

### Rolling Expectancy
Expected profit per trade over the last 100 trades.
Formula: `(Win Rate × Avg Win) - (Loss Rate × Avg Loss)`

### Equity Curve
Complete account value progression over time.

## Files

### Core Modules
- `bot/institutional_disclaimers.py` - Centralized disclaimers
- `bot/validation_layer.py` - Mathematical validation
- `bot/performance_tracking_layer.py` - Live performance tracking
- `bot/marketing_layer.py` - Public-facing reports
- `bot/statistical_reporting_module.py` - Statistical analysis

### Documentation
- `INSTITUTIONAL_GRADE_FEATURES.md` - Complete guide
- `STATISTICAL_REPORTING_QUICK_REF.md` - This file

### Examples
- `bot/institutional_grade_integration_example.py` - Usage examples

## Report Outputs

All reports include appropriate disclaimers:
- ✅ Validation disclaimer
- ✅ Performance disclaimer
- ✅ Risk disclaimer

### JSON Report
```json
{
  "report_date": "2026-02-15T00:00:00",
  "disclaimers": { ... },
  "key_statistics": {
    "win_rate_last_100_trades": { ... },
    "max_drawdown": { ... },
    "rolling_expectancy": { ... },
    "equity_curve": { ... }
  }
}
```

### Text Report
```
================================================================================
NIJA TRADING BOT - INVESTOR PERFORMANCE REPORT
================================================================================

[DISCLAIMERS]

PERFORMANCE STATISTICS
--------------------------------------------------------------------------------
Total Trades: 100
Win Rate (Last 100): 65.00%
Max Drawdown: 5.25%
Rolling Expectancy: $35.50
Total Return: 15.75%

================================================================================
```

### CSV Export (Equity Curve)
```csv
timestamp,balance,trade_count
2026-02-01T00:00:00,10000.00,0
2026-02-01T12:00:00,10050.00,1
2026-02-02T00:00:00,10100.00,2
...
```

## Best Practices

1. ✅ Always display disclaimers with performance data
2. ✅ Use Validation Layer for backtesting only
3. ✅ Use Performance Tracking Layer for live trading only
4. ✅ Generate reports regularly for audit trail
5. ✅ Export equity curves for visual review
6. ✅ Monitor all four key statistics continuously

## Disclaimer

All features include appropriate disclaimers:

```
╔════════════════════════════════════════════════════════════════════════════╗
║                      MATHEMATICAL VALIDATION ONLY                          ║
║          DOES NOT REPRESENT HISTORICAL OR FORWARD PERFORMANCE              ║
╚════════════════════════════════════════════════════════════════════════════╝

PERFORMANCE DISCLAIMER:
Past performance is not indicative of future results. All trading involves risk.

RISK DISCLAIMER:
Trading cryptocurrencies carries substantial risk of loss.
```
