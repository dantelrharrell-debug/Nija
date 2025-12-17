#!/bin/bash

OUTPUT="git_analysis.txt"

{
    echo "=========================================="
    echo "COMMIT HISTORY (Last 5)"
    echo "=========================================="
    git log --oneline -5
    
    echo ""
    echo "=========================================="
    echo "CURRENT GIT STATUS"
    echo "=========================================="
    git status
    
    echo ""
    echo "=========================================="
    echo "WHAT'S IN LAST COMMIT?"
    echo "=========================================="
    git show --stat HEAD
    
    echo ""
    echo "=========================================="
    echo "DIFF: Local vs Git Repository"
    echo "=========================================="
    echo "Checking bot.py:"
    git diff HEAD -- bot.py | head -20 || echo "No changes in bot.py"
    
    echo ""
    echo "Checking trading_strategy.py:"
    git diff HEAD -- bot/trading_strategy.py | head -30 || echo "No changes"
    
    echo ""
    echo "Checking broker_manager.py:"
    git diff HEAD -- bot/broker_manager.py | head -30 || echo "No changes"
    
    echo ""
    echo "Checking nija_apex_strategy_v71.py:"
    git diff HEAD -- bot/nija_apex_strategy_v71.py | head -20 || echo "No changes"
    
    echo ""
    echo "=========================================="
    echo "VERIFICATION: What's actually in git repo?"
    echo "=========================================="
    echo "bot.py line 59 (from git):"
    git show HEAD:bot.py | sed -n '59p'
    
    echo ""
    echo "trading_strategy.py line 185 (from git):"
    git show HEAD:bot/trading_strategy.py | sed -n '185p'
    
    echo ""
    echo "broker_manager.py line 374 (from git):"
    git show HEAD:bot/broker_manager.py | sed -n '374p'
    
    echo ""
    echo "nija_apex_strategy_v71.py line 60 (from git):"
    git show HEAD:bot/nija_apex_strategy_v71.py | sed -n '60p'
    
} > "$OUTPUT" 2>&1

cat "$OUTPUT"
echo ""
echo "=========================================="
echo "Analysis saved to: $OUTPUT"
echo "=========================================="
