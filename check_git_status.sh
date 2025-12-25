#!/bin/bash

echo "=========================================="
echo "GIT STATUS CHECK"
echo "=========================================="
echo ""

echo "📋 Modified files:"
git status --short

echo ""
echo "=========================================="
echo "LAST COMMIT INFO"
echo "=========================================="
git log -1 --oneline

echo ""
echo "=========================================="
echo "CHECKING KEY FILES FOR CHANGES"
echo "=========================================="

echo ""
echo "🔍 bot.py (line 59 - should be 30s):"
sed -n '59p' bot.py

echo ""
echo "🔍 bot/trading_strategy.py (lines 183-186 - cache variables):"
sed -n '183,186p' bot/trading_strategy.py

echo ""
echo "🔍 bot/trading_strategy.py (line 252 - cache check):"
sed -n '252p' bot/trading_strategy.py

echo ""
echo "🔍 bot/broker_manager.py (line 371 - retry logic):"
sed -n '371p' bot/broker_manager.py

echo ""
echo "🔍 bot/nija_apex_strategy_v71.py (line 60 - volume threshold):"
sed -n '60p' bot/nija_apex_strategy_v71.py

echo ""
echo "=========================================="
echo "GIT DIFF FOR BOT FILES"
echo "=========================================="
git diff HEAD -- bot.py bot/trading_strategy.py bot/nija_apex_strategy_v71.py bot/broker_manager.py | head -100
