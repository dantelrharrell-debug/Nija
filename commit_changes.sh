#!/bin/bash
# Commit dual-mode trading changes

cd /workspaces/Nija

echo "📦 Staging changes..."
git add bot/paper_trading.py \
        bot/run_paper_mode.sh \
        bot/run_live_mode.sh \
        bot/view_paper_account.py \
        bot/trading_strategy.py \
        README.md

echo "✅ Committing..."
git commit -m "Add dual-mode trading: LIVE (Coinbase) + PAPER (simulation)

- New: paper_trading.py - Full simulation engine with P&L tracking
- Modified: trading_strategy.py - Support LIVE/PAPER modes via PAPER_MODE env var
- New: run_paper_mode.sh - Launch in simulation mode (\$10k virtual)
- New: run_live_mode.sh - Launch in live mode (safety confirmation)
- New: view_paper_account.py - Monitor paper trading performance
- Updated: README.md - Dual-mode docs + TradingView limitations
- Note: TradingView has no paper API - this is standalone simulation
- Railway: Continues LIVE mode by default (PAPER_MODE not set)"

echo "🚀 Pushing to GitHub..."
git push

echo "✅ Done! Railway will auto-deploy in ~30 seconds"
