# Simple Profit Reports - Quick Reference

## What You Get

A simple, clean profit report covering the last 24-72 hours:

```
============================================================
PROFIT REPORT - Last 24h
============================================================

Starting equity: $1,000.00
Ending equity:   $1,001.06
Net P&L:         $+1.06 (+0.11%)

Closed trades:
  Count:      5
  Avg R:      0.28R
  Win rate:   60.0%
  Fees total: $4.61

============================================================
```

**That's it. Nothing fancy. Just the facts you need.**

## Quick Start

```python
from profit_confirmation_logger import ProfitConfirmationLogger

# Initialize
logger = ProfitConfirmationLogger(data_dir="./data")

# Generate report
logger.print_simple_report(
    starting_equity=1000.00,  # Your balance 24h ago
    ending_equity=1001.06,    # Your balance now
    hours=24                  # Time window: 24, 48, or 72 hours
)
```

## Time Windows

You can generate reports for:
- **24 hours** (default) - Yesterday to now
- **48 hours** - Two days ago to now  
- **72 hours** - Three days ago to now (maximum)

```python
# 24-hour report
logger.print_simple_report(starting_equity=1000, ending_equity=1005, hours=24)

# 48-hour report
logger.print_simple_report(starting_equity=995, ending_equity=1005, hours=48)

# 72-hour report
logger.print_simple_report(starting_equity=990, ending_equity=1005, hours=72)
```

## What Each Field Means

### Starting equity
Your account balance at the start of the time window (e.g., 24 hours ago).

### Ending equity
Your current account balance.

### Net P&L
The difference: `ending_equity - starting_equity`

Shows both dollars and percentage.

### Count
Number of closed trades during the time window.

### Avg R
Average risk/reward ratio.

- **1R** = You made exactly what you risked
- **2R** = You made 2x what you risked
- **0.5R** = You lost half of what you risked

**Example**: If you risked $10 and made $20, that's **2R**.

### Win rate
Percentage of trades that were profitable.

**Example**: 3 winners out of 5 trades = 60% win rate.

### Fees total
Total fees paid on all closed trades during the time window.

## When to Use It

### Daily Performance Check
```python
# Run at end of each trading day
logger.print_simple_report(
    starting_equity=get_balance_24h_ago(),
    ending_equity=get_current_balance(),
    hours=24
)
```

### Weekly Review
```python
# Check performance over last 3 days
logger.print_simple_report(
    starting_equity=get_balance_72h_ago(),
    ending_equity=get_current_balance(),
    hours=72
)
```

### After a Trading Session
```python
# Check today's trading results
logger.print_simple_report(
    starting_equity=balance_at_session_start,
    ending_equity=current_balance,
    hours=24
)
```

## Getting Started vs Ending Equity

**How do I know my starting equity?**

### Option 1: Save it daily
```python
# Save at start of each day
with open('daily_equity.json', 'w') as f:
    json.dump({
        'date': datetime.now().isoformat(),
        'equity': current_balance
    }, f)
```

### Option 2: Query from broker
```python
# Get historical balance (if broker supports it)
starting_equity = broker.get_balance_at_time(
    timestamp=datetime.now() - timedelta(hours=24)
)
```

### Option 3: Calculate from trades
```python
# If you have all trade history
closed_trades_pnl = sum(trade['net_profit_usd'] for trade in closed_trades)
starting_equity = current_balance - closed_trades_pnl
```

## Demo Script

Try it yourself:

```bash
python demo_profit_report.py
```

This will:
1. Simulate 5 trades
2. Generate a 24-hour report
3. Generate a 48-hour report
4. Show summary statistics

## Integration Example

```bash
python integration_example_profit_logger.py
```

This shows:
1. How to check if profit is "proven"
2. How to generate reports
3. How to track daily summaries
4. How to clean up stale tracking

## Tips

### Keep it Simple
Don't overthink it. The report is intentionally simple:
- 4 core metrics
- Clean format
- Easy to read
- No clutter

### Focus on Net P&L
The most important number: **Did you make or lose money?**

Everything else (win rate, avg R, etc.) is context.

### Track Over Time
Generate reports daily and save them:

```python
report = logger.generate_simple_report(
    starting_equity=1000,
    ending_equity=1005,
    hours=24
)

# Save to file
with open(f'reports/report_{datetime.now().strftime("%Y-%m-%d")}.txt', 'w') as f:
    f.write(report)
```

### Compare Windows
Compare 24h vs 48h vs 72h to see trends:

```python
# Short-term (24h)
logger.print_simple_report(starting_equity=1000, ending_equity=1005, hours=24)

# Medium-term (48h)
logger.print_simple_report(starting_equity=995, ending_equity=1005, hours=48)

# Longer-term (72h)
logger.print_simple_report(starting_equity=990, ending_equity=1005, hours=72)
```

## No Trades? No Problem

If you have no closed trades in the time window:

```
============================================================
PROFIT REPORT - Last 24h
============================================================

Starting equity: $1,000.00
Ending equity:   $1,000.00
Net P&L:         $+0.00

Closed trades:
  Count:      0
  Avg R:      N/A
  Win rate:   N/A
  Fees total: $0.00

============================================================
```

Clean and simple. No errors. Just "N/A" for stats that don't apply.

## Advanced: Get Raw Report Data

If you want the report as a string instead of printing:

```python
report_text = logger.generate_simple_report(
    starting_equity=1000,
    ending_equity=1005,
    hours=24
)

# Now you can:
# - Save to file
# - Send via email
# - Post to Discord/Slack
# - Display in web dashboard
# - Whatever you want
```

## That's It

No complicated setup. No fancy configuration. Just:

1. Initialize the logger
2. Call `print_simple_report()`
3. See your results

Simple. Clean. Effective.

---

**For full documentation, see**: [PROFIT_CONFIRMATION_LOGGER.md](PROFIT_CONFIRMATION_LOGGER.md)
