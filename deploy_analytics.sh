#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m "💰 Add comprehensive fee tracking & performance analytics

✨ New Features:
- Trade analytics module with complete fee tracking
- Coinbase fee calculations (0.6% taker, 0.4% maker)
- Performance metrics: win rate, P&L, profit factor
- Slippage detection and reporting
- CSV/JSON trade history export
- Session reports every 10 cycles
- Daily automatic exports

📊 Analytics Tracked:
- Entry/exit fees for every trade
- Gross vs net profit (after fees)  
- Fill price verification and slippage
- Trade duration tracking
- Best/worst trade analysis
- Profit factor calculations

🎯 Impact:
- NOW YOU'LL KNOW: Actual profit after Coinbase's 0.6% fees
- Reality check: \$1.12 position loses \$0.0067 to fees
- Visibility: See if strategy is profitable after costs
- Export: Analyze trade history in Excel/CSV

📁 Files Added:
- bot/trade_analytics.py - Complete analytics engine
- test_analytics.py - Comprehensive test suite

🔧 Files Modified:
- bot/trading_strategy.py - Integrated analytics tracking
- Records entry/exit with fee calculations
- Prints session report every 10 cycles
- Exports CSV daily

✅ Ready for: Coinbase completion before Binance migration"
git push origin main
echo "✅ Deployed - Fee tracking & analytics live!"
