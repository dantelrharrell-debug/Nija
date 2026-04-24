# Quick Reference: Security, Backtesting & Paper Trading

## 🚀 Quick Commands

### Security Scanning

```bash
# Run local security scan
pip install safety bandit
safety check
bandit -r . --exclude ./archive,./venv,./mobile,./frontend

# View GitHub security alerts
# Navigate to: Repository → Security → Code scanning alerts
```

### 5-Year Backtesting

```bash
# Quick test (1 year, synthetic data)
python run_5year_backtest.py --symbol BTC-USD --years 1 --output results/test.json

# Full 5-year backtest
python run_5year_backtest.py --symbol BTC-USD --years 5 --output results/btc_5y.json

# Multiple symbols
python run_5year_backtest.py --symbol ETH-USD --years 5 --output results/eth_5y.json
python run_5year_backtest.py --symbol SOL-USD --years 5 --output results/sol_5y.json

# Custom settings
python run_5year_backtest.py \
  --symbol BTC-USD \
  --years 3 \
  --initial-balance 50000 \
  --commission 0.0006 \
  --slippage 0.0003 \
  --output results/custom.json
```

### 30-Day Paper Trading

```bash
# Day 1: Start tracking
python run_30day_paper_trading.py --record-daily

# Set up daily cron job (run at market close)
crontab -e
# Add: 0 22 * * * cd /path/to/Nija && python run_30day_paper_trading.py --record-daily

# Weekly reports (Sunday mornings)
python run_30day_paper_trading.py --weekly-report 1
python run_30day_paper_trading.py --weekly-report 2
python run_30day_paper_trading.py --weekly-report 3
python run_30day_paper_trading.py --weekly-report 4

# Final 30-day report
python run_30day_paper_trading.py --final-report

# Compare to backtest
python run_30day_paper_trading.py \
  --compare-backtest results/btc_5y.json \
  --final-report
```

## 📊 Understanding the Output

### Backtest Results

**Key Metrics:**
- **Sharpe Ratio**: > 1.5 is good, > 2.0 is excellent
- **Profit Factor**: > 2.0 is strong
- **Win Rate**: 55-65% is ideal
- **Max Drawdown**: < 15% is acceptable, < 12% is excellent
- **P-Value**: < 0.05 shows statistical significance

**Regime Performance:**
Look for consistent performance across all regimes. Strategy should work in:
- Bull markets (positive drift)
- Bear markets (negative drift)
- Ranging markets (sideways)
- Volatile markets (high volatility)

### Paper Trading Metrics

**Daily Tracking:**
- Daily P&L should average positive
- Win rate should match backtest (±10%)
- Max drawdown should not exceed backtest

**Alerts to Watch:**
- 🔴 Daily loss > 5% (high severity)
- 🟡 Win rate < 40% (medium severity)
- 🔴 Drawdown > 12% (high severity)
- 🟡 Exposure > 80% (medium severity)

## ✅ Success Criteria

### Before Going Live

**Security:**
- [ ] Zero high/critical vulnerabilities
- [ ] All dependencies up to date
- [ ] No secrets in codebase

**Backtesting:**
- [ ] Sharpe > 1.5 across all regimes
- [ ] Profit factor > 2.0
- [ ] Win rate > 55%
- [ ] Max DD < 15%
- [ ] P-value < 0.05

**Paper Trading:**
- [ ] 30 days completed
- [ ] Performance within 10% of backtest
- [ ] Max DD < backtest max DD
- [ ] No critical alerts
- [ ] Sharpe > 1.5

## 🛠️ Troubleshooting

### "No module named 'pandas'"
```bash
pip install -r requirements.txt
```

### "Data file not found"
Script auto-generates synthetic data for testing. For real backtests:
1. Download historical data from exchange
2. Save as CSV: `data/SYMBOL_historical_5y.csv`
3. Format: `timestamp,open,high,low,close,volume`

### Security scan fails
```bash
# Update packages
pip install --upgrade safety bandit

# Check specific issues
bandit -r bot/ -ll  # Only high/medium severity
safety check --continue-on-error
```

### Paper trading shows no data
```bash
# Check data directory
ls -la data/paper_trading_30day/

# Initialize if needed
mkdir -p data/paper_trading_30day
python run_30day_paper_trading.py --record-daily
```

## 📁 File Locations

```
.github/workflows/
├── codeql.yml              # CodeQL security scanning
└── security-scan.yml       # Dependency & secret scanning

results/
├── test_backtest.json      # Test backtest output
├── btc_5y.json            # 5-year BTC backtest
└── *.json                 # Other backtest results

data/
├── paper_trading_30day/   # Paper trading data
│   ├── daily_metrics.json
│   ├── alerts.json
│   └── *.json
└── *_historical_5y.csv    # Historical data (optional)

Documentation:
├── HIGH_LEVERAGE_IMPROVEMENTS.md      # Complete guide
├── SECURITY_HARDENING_GUIDE.md        # Security best practices
└── QUICK_REFERENCE_IMPROVEMENTS.md    # This file
```

## 🔗 Resources

- **Complete Guide**: [HIGH_LEVERAGE_IMPROVEMENTS.md](HIGH_LEVERAGE_IMPROVEMENTS.md)
- **Security Guide**: [SECURITY_HARDENING_GUIDE.md](SECURITY_HARDENING_GUIDE.md)
- **Backtesting Guide**: [LIVE_EXECUTION_BACKTESTING_GUIDE.md](LIVE_EXECUTION_BACKTESTING_GUIDE.md)
- **Strategy Docs**: [APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)

## 💡 Pro Tips

1. **Run backtests on multiple timeframes**: 1yr, 3yr, 5yr to validate consistency
2. **Test multiple symbols**: BTC, ETH, SOL, etc. to verify strategy generalizability
3. **Compare regimes**: Strategy should work in ALL market conditions
4. **Paper trade in parallel**: Run multiple strategies to compare
5. **Set up alerts**: Monitor daily for performance degradation
6. **Keep records**: Save all backtest and paper trading reports for audit trail

## 🎯 Next Steps

After completing all three improvements:

1. **Week 1**: Fix security issues, update dependencies
2. **Week 2**: Run comprehensive backtests on top 5 symbols
3. **Week 3-6**: 30-day paper trading with daily monitoring
4. **Week 7**: Review results, make go/no-go decision
5. **Week 8+**: Start live with minimal capital, scale gradually
