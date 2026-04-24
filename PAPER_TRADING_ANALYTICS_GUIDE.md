# NIJA Paper Trading Analytics Guide

## Overview

The NIJA Paper Trading Analytics System implements a **3-phase optimization process** for systematically improving trading performance before deploying real capital:

1. **📊 Phase 1: Run Paper Trading with Analytics ON**
   - Collect 100-300 trades with full analytics
   - Track performance by signal type (Dual RSI, breakout, etc.)
   - Track performance by exit strategy (profit target, stop loss, etc.)
   - Gather at least 1-2 weeks of data

2. **⚔️ Phase 2: Kill Losers Ruthlessly**
   - Identify underperforming signal types (bottom 25%)
   - Disable signals with negative P&L or low win rates
   - Reduce capital allocation to weak exit strategies
   - Promote top-quartile strategies only

3. **🎯 Phase 3: Lock "Profit-Ready" Definition**
   - Define specific profitability criteria
   - Validate metrics: return %, drawdown %, Sharpe ratio
   - Check operational metrics: scan time, utilization
   - Only scale to live trading when criteria met

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Paper Trading Bot                          │
│  - Executes trades with virtual money                       │
│  - Records every trade with full context                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│              Analytics Engine                                │
│  - Tracks signal type performance                           │
│  - Tracks exit strategy performance                         │
│  - Calculates win rates, profit factors, Sharpe ratios      │
│  - Identifies top and bottom performers                     │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│            Performance Optimizer                             │
│  - Disables underperforming signals                         │
│  - Reduces allocation to weak exits                         │
│  - Promotes top-quartile strategies                         │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│         Profit-Ready Validator                               │
│  - Validates all criteria met                               │
│  - Generates readiness report                               │
│  - Gates transition to live trading                         │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Run Demo (Recommended First)

```bash
# Generate 150 simulated trades to see how the system works
python demo_paper_analytics.py --trades 150

# This creates demo data in ./data/demo_paper_analytics
```

### 2. View Analytics Report

```bash
# View comprehensive performance report
python paper_trading_manager.py --data-dir ./data/demo_paper_analytics --report

# Save report to file
python paper_trading_manager.py --report --output analytics_report.json
```

### 3. Analyze Performance

```bash
# Identify top and bottom performers
python paper_trading_manager.py --analyze
```

### 4. Kill Losers

```bash
# Disable underperformers (interactive with confirmation)
python paper_trading_manager.py --kill-losers

# Auto-confirm (use in automated workflows)
python paper_trading_manager.py --kill-losers --auto-confirm
```

### 5. Check Profit-Ready Status

```bash
# Validate if ready for live trading
python paper_trading_manager.py --check-ready

# View current criteria
python paper_trading_manager.py --show-criteria
```

## Signal Types Tracked

The system tracks performance for these signal types:

| Signal Type | Description |
|------------|-------------|
| `dual_rsi` | Dual RSI strategy (RSI_9 + RSI_14) |
| `rsi_oversold` | Single RSI oversold condition |
| `rsi_overbought` | Single RSI overbought condition |
| `breakout` | Price breakout signals |
| `trend_following` | Momentum trend signals |
| `mean_reversion` | Mean reversion signals |
| `volatility_expansion` | Volatility-based signals |
| `webhook` | TradingView webhook signals |

## Exit Strategies Tracked

The system tracks performance for these exit strategies:

| Exit Strategy | Description |
|--------------|-------------|
| `profit_target` | Hit profit target |
| `stop_loss` | Hit stop loss |
| `trailing_stop` | Trailing stop triggered |
| `partial_profit` | Partial profit taking |
| `time_exit` | Time-based exit |
| `signal_reversal` | Opposite signal triggered |
| `manual` | Manual exit |

## Profit-Ready Criteria

### Default Criteria

```python
# Return criteria
min_total_return_pct: 5.0          # Minimum 5% return
min_trades: 100                     # Minimum 100 trades
max_trades: 300                     # Max before decision required

# Risk criteria
max_drawdown_pct: 15.0             # Maximum 15% drawdown
min_sharpe_ratio: 1.0              # Minimum Sharpe ratio

# Performance criteria
min_win_rate: 45.0                 # Minimum 45% win rate
min_profit_factor: 1.5             # Minimum 1.5 profit factor

# Operational criteria
max_scan_time_seconds: 30.0        # Maximum 30s scan time
min_utilization_pct: 60.0          # Minimum 60% capital usage
max_utilization_pct: 80.0          # Maximum 80% capital usage

# Time criteria
min_days_trading: 14               # Minimum 14 days
```

### Customizing Criteria

```bash
# Set custom profit-ready criteria
python paper_trading_manager.py --set-criteria \
  --min-return 10 \
  --max-drawdown 12 \
  --min-sharpe 1.5 \
  --min-win-rate 50 \
  --min-profit-factor 2.0
```

## Performance Metrics

### Signal Performance Metrics

For each signal type, we track:

- **Total Trades**: Number of trades using this signal
- **Win Rate**: Percentage of winning trades
- **Profit Factor**: Gross profit / Gross loss
- **Total P&L**: Net profit/loss
- **Average P&L**: Average P&L per trade
- **Sharpe Ratio**: Risk-adjusted returns
- **Average Duration**: Average trade duration
- **Enabled**: Whether signal is currently enabled

### Exit Performance Metrics

For each exit strategy, we track:

- **Total Trades**: Number of trades using this exit
- **Win Rate**: Percentage of winning trades
- **Profit Factor**: Gross profit / Gross loss
- **Total P&L**: Net profit/loss
- **Average P&L**: Average P&L per trade
- **Capital Allocation**: Current allocation percentage

## Integration with Existing System

### Recording Trades from Live Bot

```python
from bot.paper_trading_analytics import get_analytics, TradeAnalytics, SignalType, ExitReason

# Get analytics instance
analytics = get_analytics(data_dir="./data/paper_analytics")

# After each trade completes, record it
trade = TradeAnalytics(
    trade_id="TRADE-001",
    timestamp=datetime.now().isoformat(),
    symbol="BTC-USD",
    signal_type=SignalType.DUAL_RSI.value,
    entry_price=50000.0,
    entry_size_usd=200.0,
    entry_time=entry_time.isoformat(),
    exit_reason=ExitReason.PROFIT_TARGET.value,
    exit_price=50500.0,
    exit_time=exit_time.isoformat(),
    gross_pnl=100.0,
    net_pnl=98.8,  # After fees
    pnl_pct=2.0,
    duration_minutes=45,
    max_favorable_excursion=150.0,
    max_adverse_excursion=50.0,
    risk_reward_ratio=3.0,
    scan_time_seconds=15.0,
    rsi_9=35.0,
    rsi_14=40.0
)

analytics.record_trade(trade)
```

### Checking if Signal is Disabled

```python
from bot.paper_trading_analytics import get_analytics

analytics = get_analytics()

# Before executing a trade, check if signal is disabled
signal_type = "dual_rsi"
if signal_type in analytics.signal_performance:
    if not analytics.signal_performance[signal_type].enabled:
        print(f"Signal {signal_type} is disabled - skipping trade")
        return
```

### Getting Exit Capital Allocation

```python
from bot.paper_trading_analytics import get_analytics

analytics = get_analytics()

# Get current allocation for an exit strategy
exit_reason = "profit_target"
if exit_reason in analytics.exit_performance:
    allocation = analytics.exit_performance[exit_reason].capital_allocation_pct
    # Adjust position size based on allocation
    adjusted_size = base_size * (allocation / 100.0)
```

## Workflow Example

### Week 1-2: Data Collection

```bash
# Run paper trading bot with analytics enabled
# Let it trade for 1-2 weeks
# Aim for 100-300 trades

# Check progress periodically
python paper_trading_manager.py --report
```

### After Data Collection: Analysis

```bash
# Analyze performance
python paper_trading_manager.py --analyze

# Output will show:
# - Top performers (top 25%)
# - Underperformers (bottom 25%)
```

### Phase 2: Kill Losers

```bash
# Review underperformers and disable them
python paper_trading_manager.py --kill-losers

# This will:
# - Disable underperforming signals
# - Reduce allocation for weak exits (50% reduction)
```

### Continue Trading: 20-50 More Trades

```bash
# Monitor performance with optimized settings
# Collect 20-50 more trades to validate improvements

python paper_trading_manager.py --report
```

### Phase 3: Validate Profit-Ready

```bash
# Check if ready for live trading
python paper_trading_manager.py --check-ready

# If all criteria met:
# ✅ Ready to scale to live trading
```

## Reports and Analytics

### Analytics Report Format

```json
{
  "summary": {
    "total_trades": 150,
    "total_pnl": 2500.50,
    "win_rate": 52.5,
    "avg_pnl_per_trade": 16.67
  },
  "signal_performance": {
    "dual_rsi": {
      "total_trades": 45,
      "win_rate": 55.6,
      "profit_factor": 1.8,
      "total_pnl": 1200.00,
      "enabled": true
    },
    "webhook": {
      "total_trades": 20,
      "win_rate": 35.0,
      "profit_factor": 0.7,
      "total_pnl": -300.00,
      "enabled": false
    }
  },
  "exit_performance": {
    "profit_target": {
      "total_trades": 60,
      "win_rate": 65.0,
      "profit_factor": 2.5,
      "capital_allocation_pct": 100.0
    }
  },
  "profit_ready_status": {
    "is_ready": true,
    "message": "✅ All criteria met!",
    "criteria_met": {
      "min_trades": true,
      "min_win_rate": true,
      "max_drawdown": true
    }
  }
}
```

## Best Practices

### 1. Data Collection Phase

- ✅ **Do**: Run for at least 14 days
- ✅ **Do**: Aim for 100-300 trades
- ✅ **Do**: Let the bot trade naturally without interference
- ❌ **Don't**: Stop early with insufficient data
- ❌ **Don't**: Cherry-pick trades

### 2. Kill Losers Phase

- ✅ **Do**: Review underperformers carefully
- ✅ **Do**: Consider market conditions (was it a bad week?)
- ✅ **Do**: Monitor for 20-50 trades after changes
- ❌ **Don't**: Disable everything at once
- ❌ **Don't**: Make changes too frequently

### 3. Profit-Ready Validation

- ✅ **Do**: Set realistic criteria for your account size
- ✅ **Do**: Validate across different market conditions
- ✅ **Do**: Be patient - wait for all criteria to be met
- ❌ **Don't**: Lower criteria to force early graduation
- ❌ **Don't**: Skip validation to rush to live trading

## Troubleshooting

### No Trades Recorded

**Problem**: Analytics report shows 0 trades

**Solution**:
1. Verify paper trading bot is running
2. Check that trades are being recorded to analytics
3. Verify data directory path is correct

### Criteria Never Met

**Problem**: Never meets profit-ready criteria

**Solution**:
1. Review and potentially adjust criteria
2. May need strategy tuning before scaling
3. Consider if market conditions are unfavorable

### Too Many Disabled Signals

**Problem**: All or most signals get disabled

**Solution**:
1. May indicate strategy needs fundamental improvement
2. Review if criteria for "underperformer" is too strict
3. Consider market regime - may need regime-specific strategies

## Advanced Usage

### Custom Performance Analysis

```python
from bot.paper_trading_analytics import get_analytics

analytics = get_analytics()

# Get trades for specific signal
dual_rsi_trades = [t for t in analytics.trades if t.signal_type == "dual_rsi"]

# Calculate custom metrics
avg_duration = sum(t.duration_minutes for t in dual_rsi_trades) / len(dual_rsi_trades)
best_trade = max(dual_rsi_trades, key=lambda t: t.net_pnl)
```

### Automated Daily Reports

```bash
# Add to cron or scheduled task
0 0 * * * cd /path/to/nija && python paper_trading_manager.py --report --output daily_report_$(date +\%Y\%m\%d).json
```

### Integration with Monitoring

```python
from bot.paper_trading_analytics import get_analytics

analytics = get_analytics()

# Check profit-ready status programmatically
status = analytics.validate_profit_ready()

if status.is_ready:
    # Send notification, update dashboard, etc.
    send_notification("✅ Bot is profit-ready for live trading!")
```

## Files and Directories

```
data/paper_analytics/          # Analytics data directory
├── trades_analytics.json      # All recorded trades
├── signal_performance.json    # Signal type performance
├── exit_performance.json      # Exit strategy performance
├── profit_ready_criteria.json # Profit-ready criteria config
└── disabled_signals.json      # List of disabled signals
```

## Summary

The Paper Trading Analytics System provides a **data-driven, systematic approach** to:

1. ✅ **Collect comprehensive performance data** (100-300 trades, 1-2 weeks)
2. ✅ **Identify and eliminate losers** (bottom 25% signals and exits)
3. ✅ **Validate profit-readiness** before scaling to live trading

This process ensures you only deploy strategies that have **proven profitability** in paper trading, dramatically reducing the risk of losses when transitioning to real money.

---

**Next Steps**:
1. Run the demo: `python demo_paper_analytics.py`
2. Review the report: `python paper_trading_manager.py --data-dir ./data/demo_paper_analytics --report`
3. Integrate with your live paper trading bot
4. Follow the 3-phase process to achieve consistent profitability
