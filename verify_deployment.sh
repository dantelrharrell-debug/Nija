#!/bin/bash

echo "=========================================="
echo "RECENT COMMITS"
echo "=========================================="
git log --oneline -5

echo ""
echo "=========================================="
echo "LAST COMMIT DETAILS"
echo "=========================================="
git log -1 --stat

echo ""
echo "=========================================="
echo "FILES IN LAST COMMIT"
echo "=========================================="
git show --name-only --pretty="" HEAD

echo ""
echo "=========================================="
echo "VERIFY CODE CHANGES IN REPOSITORY"
echo "=========================================="
echo ""
echo "🔍 bot.py line 59 (in git repo):"
git show HEAD:bot.py | sed -n '59p'

echo ""
echo "🔍 trading_strategy.py lines 183-186 (in git repo):"
git show HEAD:bot/trading_strategy.py | sed -n '183,186p'

echo ""
echo "🔍 broker_manager.py line 371 (in git repo):"
git show HEAD:bot/broker_manager.py | sed -n '371p' || echo "Line 371 not found - checking nearby..."
git show HEAD:bot/broker_manager.py | sed -n '370,375p'

echo ""
echo "🔍 nija_apex_strategy_v71.py line 60 (in git repo):"
git show HEAD:bot/nija_apex_strategy_v71.py | sed -n '60p'
