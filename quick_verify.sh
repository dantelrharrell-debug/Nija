#!/bin/bash

echo "===================="
echo "COMMIT VERIFICATION"
echo "===================="
echo ""

# Get the last commit message
echo "📝 Last commit message:"
git log -1 --pretty=format:"%s%n%b" | head -20
echo ""
echo ""

# Show what files changed
echo "📂 Files changed in last commit:"
git diff --name-only HEAD~1 HEAD
echo ""

# Check if our key changes are in the repo
echo "===================="
echo "CODE VERIFICATION"
echo "===================="
echo ""

echo "1️⃣ bot.py - Scan interval (line 59):"
git show HEAD:bot.py | grep -A1 "time.sleep"
echo ""

echo "2️⃣ trading_strategy.py - Cache init (lines 183-186):"
git show HEAD:bot/trading_strategy.py | grep -A3 "_price_cache"
echo ""

echo "3️⃣ trading_strategy.py - Cache check (search for 'Using cached'):"
git show HEAD:bot/trading_strategy.py | grep -B2 -A2 "Using cached"
echo ""

echo "4️⃣ broker_manager.py - Retry logic (search for 'max_retries'):"
git show HEAD:bot/broker_manager.py | grep -A5 "max_retries = 3"
echo ""

echo "5️⃣ nija_apex_strategy_v71.py - Volume threshold (line 60):"
git show HEAD:bot/nija_apex_strategy_v71.py | grep "volume_threshold"
echo ""

echo "===================="
echo "✅ VERIFICATION COMPLETE"
echo "===================="
