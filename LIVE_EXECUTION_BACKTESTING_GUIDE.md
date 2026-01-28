# NIJA Live Execution + Backtesting Engine Guide

## 🎯 Overview

The NIJA Live Execution + Backtesting Engine provides a comprehensive framework for:

- **Real Money Validation**: Track live trades and validate strategy performance
- **Proof of Performance**: Generate investor-grade performance reports
- **Investor-Grade Track Record**: Detailed metrics and analytics
- **Confidence to Scale Capital**: Backtesting and live comparison tools

## 📦 Components

### 1. Unified Backtest Engine (`bot/unified_backtest_engine.py`)

Comprehensive backtesting engine with:
- Multiple strategy support
- Detailed performance metrics (Sharpe, Sortino, Profit Factor, Win Rate, etc.)
- Regime-aware analysis
- Trade-by-trade breakdown
- Equity curve generation
- Export to JSON/HTML

### 2. Live Execution Tracker (`bot/live_execution_tracker.py`)

Real-time trade tracking with:
- Real-time performance monitoring
- Trade validation and logging
- Risk monitoring and alerts
- Circuit breakers for daily loss limits
- Automatic daily summaries
- Export to CSV

### 3. CLI Interface (`nija_execution_cli.py`)

Unified command-line interface for:
- Running backtests
- Monitoring live execution
- Generating performance reports
- Comparing backtest vs live performance

## 🚀 Quick Start

### Installation

Dependencies are already in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### Running a Backtest

```bash
# Run backtest on BTC-USD with historical data
python nija_execution_cli.py backtest \
  --symbol BTC-USD \
  --data data/BTC-USD_1h.csv \
  --initial-balance 10000 \
  --days 90 \
  --output results/backtest_btc.json
```

**Options:**
- `--symbol`: Trading symbol (e.g., BTC-USD, ETH-USD)
- `--data`: Path to historical OHLCV CSV file
- `--initial-balance`: Starting balance (default: $10,000)
- `--commission`: Commission rate (default: 0.001 = 0.1%)
- `--slippage`: Slippage rate (default: 0.0005 = 0.05%)
- `--days`: Number of days to backtest (from end of data)
- `--output`: Output file for results (JSON format)
- `--strategy`: Strategy to use (apex_v71, apex_v72, enhanced)

### Monitoring Live Execution

```bash
# Monitor live trading execution
python nija_execution_cli.py live \
  --balance 10000 \
  --max-daily-loss 5.0 \
  --max-drawdown 12.0 \
  --export-csv
```

**Options:**
- `--balance`: Current account balance
- `--data-dir`: Directory for storing tracking data (default: ./data/live_tracking)
- `--max-daily-loss`: Maximum daily loss % before circuit breaker (default: 5%)
- `--max-drawdown`: Maximum drawdown % for alerts (default: 12%)
- `--export-csv`: Export trades to CSV

### Generating Performance Reports

```bash
# Generate report from backtest and live data
python nija_execution_cli.py report \
  --backtest results/backtest_btc.json \
  --live data/live_tracking \
  --format text
```

**Options:**
- `--backtest`: Path to backtest results JSON
- `--live`: Path to live tracking data directory
- `--output`: Output file path
- `--format`: Report format (text, json, html)

### Comparing Backtest vs Live

```bash
# Compare backtest vs live performance
python nija_execution_cli.py compare \
  --backtest results/backtest_btc.json \
  --live data/live_tracking
```

## 📊 Performance Metrics

The engine tracks elite-tier performance metrics:

| Metric | Description | Elite Target |
|--------|-------------|--------------|
| **Profit Factor** | Total wins ÷ Total losses | 2.0 - 2.6 |
| **Win Rate** | % of winning trades | 58% - 62% |
| **Sharpe Ratio** | Risk-adjusted returns | > 1.8 |
| **Sortino Ratio** | Downside risk-adjusted returns | > 1.8 |
| **Max Drawdown** | Maximum peak-to-trough decline | < 12% |
| **Avg Win** | Average winning trade | ~0.9% - 1.5% |
| **Avg Loss** | Average losing trade | -0.4% to -0.7% |
| **Risk:Reward** | Avg win ÷ Avg loss | 1:1.8 - 1:2.5 |
| **Expectancy** | Expected profit per trade | +$0.45 - $0.65 per $1 risked |

## 🔧 Integration with NIJA Strategies

### Using with APEX v7.1 Strategy

```python
from bot.unified_backtest_engine import UnifiedBacktestEngine
from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71

# Create backtest engine
engine = UnifiedBacktestEngine(
    initial_balance=10000.0,
    commission_pct=0.001,
    slippage_pct=0.0005
)

# Initialize strategy
strategy = NIJAApexStrategyV71(broker_client=None)

# Run backtest loop (integrate with strategy signals)
# ... (see example in unified_backtest_engine.py)

# Calculate and print results
results = engine.calculate_metrics()
results.print_summary()
```

### Recording Live Trades

```python
from bot.live_execution_tracker import LiveExecutionTracker

# Initialize tracker
tracker = LiveExecutionTracker(
    initial_balance=10000.0,
    max_daily_loss_pct=5.0,
    max_drawdown_pct=12.0
)

# Record trade entry (when opening position)
tracker.record_entry(
    trade_id="BTC-001",
    symbol="BTC-USD",
    side="long",
    entry_price=50000.0,
    size=0.1,
    stop_loss=49000.0,
    take_profit=52000.0,
    commission=5.0
)

# Record trade exit (when closing position)
tracker.record_exit(
    trade_id="BTC-001",
    exit_price=51000.0,
    exit_reason="take_profit",
    commission=5.1
)

# Get performance snapshot
snapshot = tracker.get_performance_snapshot(current_balance=10090.0)
print(f"Win Rate: {snapshot.win_rate*100:.1f}%")
print(f"Total P&L: ${snapshot.realized_pnl_total:+.2f}")
```

## 📈 Workflow Examples

### 1. Strategy Development Workflow

```bash
# Step 1: Run backtest on historical data
python nija_execution_cli.py backtest \
  --symbol BTC-USD \
  --data data/BTC-USD_1h.csv \
  --initial-balance 10000 \
  --days 180 \
  --output results/backtest_6months.json

# Step 2: Review backtest results
# Check if metrics meet elite targets (Profit Factor > 2.0, Win Rate 58-62%, etc.)

# Step 3: If backtest looks good, start live trading with small capital
# Monitor with live tracker

# Step 4: Compare backtest vs live after 30 days
python nija_execution_cli.py compare \
  --backtest results/backtest_6months.json \
  --live data/live_tracking
```

### 2. Daily Monitoring Workflow

```bash
# Morning: Check current status
python nija_execution_cli.py live --balance <current_balance>

# Throughout day: Live tracker runs automatically (integrated with bot)

# End of day: Generate daily report
python nija_execution_cli.py report \
  --live data/live_tracking \
  --format text
```

### 3. Investor Reporting Workflow

```bash
# Generate monthly performance report
python nija_execution_cli.py report \
  --backtest results/backtest.json \
  --live data/live_tracking \
  --format json \
  --output reports/monthly_$(date +%Y%m).json

# Future: Convert to PDF/HTML for investor presentation
```

## 🛡️ Risk Management Features

### Circuit Breakers

The live tracker includes automatic circuit breakers:

1. **Daily Loss Limit**: Triggers alert when daily loss exceeds threshold (default: 5%)
2. **Max Drawdown Alert**: Warns when drawdown exceeds threshold (default: 12%)

Example alert:
```
================================================================================
🚨 CIRCUIT BREAKER: Daily loss limit exceeded!
   Daily P&L: $-520.00 (-5.2%)
   Limit: -5.0%
   ACTION REQUIRED: Stop trading for today
================================================================================
```

### Position Validation

Before opening positions, the engine validates:
- Sufficient balance
- Position size within risk limits
- Stop loss and take profit levels set

### Performance Monitoring

Real-time monitoring of:
- Win rate
- Profit factor
- Sharpe ratio
- Drawdown
- Open positions
- Daily P&L

## 📁 Data Structure

### Historical Data CSV Format

CSV files should have these columns:
```csv
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,50000.0,50500.0,49800.0,50200.0,100.5
2024-01-01 01:00:00,50200.0,50800.0,50100.0,50600.0,120.3
...
```

Alternative column names are supported:
- `time`, `date` instead of `timestamp`
- Standard OHLCV format

### Live Tracking Data

Stored in `data/live_tracking/` (configurable):
- `tracker_state.json`: Current state with all trades
- `trades_YYYYMMDD.csv`: Daily trade exports

## 🎯 Integration Points

### With Existing NIJA Components

1. **Execution Engine** (`bot/execution_engine.py`):
   - Add calls to `tracker.record_entry()` when opening positions
   - Add calls to `tracker.record_exit()` when closing positions

2. **Broker Integration** (`bot/broker_integration.py`):
   - Log actual commission and slippage
   - Track order execution quality

3. **Trading Strategy** (`bot/trading_strategy.py`):
   - Use backtesting engine to validate strategy changes
   - Compare live performance with backtest

4. **Dashboard** (`bot/dashboard_server.py`):
   - Display live tracker metrics
   - Show equity curve from backtest engine

## 🔍 Troubleshooting

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'pandas'`
```bash
# Solution: Install dependencies
pip install -r requirements.txt
```

**Issue**: `FileNotFoundError: data/BTC-USD_1h.csv`
```bash
# Solution: Ensure historical data file exists
# Download or generate OHLCV data for backtesting
```

**Issue**: Live tracker shows no trades
```bash
# Solution: Ensure tracker is integrated with execution engine
# Check that record_entry() and record_exit() are being called
```

## 📚 Next Steps

### Immediate Enhancements

1. **Strategy Integration**: Connect backtest engine with actual NIJA APEX strategies
2. **HTML Reports**: Implement HTML report generation with charts
3. **Multi-Symbol Backtesting**: Run backtests across multiple symbols simultaneously
4. **Walk-Forward Analysis**: Implement walk-forward optimization
5. **Monte Carlo Simulation**: Add Monte Carlo analysis for robustness testing

### Future Features

1. **Real-Time Dashboard**: Web-based dashboard for live monitoring
2. **Automated Reporting**: Scheduled email reports
3. **Performance Comparison**: Compare multiple strategies side-by-side
4. **Risk Alerts**: SMS/Email alerts for circuit breakers
5. **Cloud Storage**: Export data to cloud (S3, Google Cloud)

## 🏆 Success Metrics

Track these metrics to ensure the engine meets investor-grade standards:

✅ **Backtesting**
- [ ] Profit Factor > 2.0
- [ ] Win Rate 58-62%
- [ ] Sharpe Ratio > 1.8
- [ ] Max Drawdown < 12%
- [ ] 100+ trades in backtest

✅ **Live Trading**
- [ ] Live performance within 10% of backtest
- [ ] No circuit breaker triggers in first 30 days
- [ ] Positive expectancy maintained
- [ ] Risk limits honored on all trades

✅ **Reporting**
- [ ] Daily performance summaries generated
- [ ] Monthly investor reports created
- [ ] Trade log complete and accurate
- [ ] Performance metrics tracked in real-time

## 📞 Support

For issues or questions:
1. Check this guide first
2. Review code comments in the source files
3. Check existing NIJA documentation (README.md, APEX_V71_DOCUMENTATION.md)
4. Open an issue on GitHub

---

**Version**: 1.0  
**Last Updated**: January 28, 2026  
**Author**: NIJA Trading Systems
