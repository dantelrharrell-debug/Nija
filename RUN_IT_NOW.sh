#!/bin/bash
set -e

cd /workspaces/Nija

# Step 1: Create data directories
mkdir -p /usr/src/app/data
mkdir -p /workspaces/Nija/data

# Step 2: Fix apex_config.py
git checkout -- bot/apex_config.py 2>/dev/null || true

python3 << 'EOF'
import re
with open('bot/apex_config.py', 'r') as f:
    content = f.read()
content = re.sub(r"'max_positions':\s*5,", "'max_positions': 8,", content)
with open('bot/apex_config.py', 'w') as f:
    f.write(content)
print("✅ Fixed max_positions: 5 → 8")
EOF

# Step 3: Add and commit all changes
git add -A

git commit -m "Apply NIJA sell logic to existing 10 positions + fix max_positions to 8

FIXES:
- apex_config.py: max_positions 5 → 8 (was holding 10, reducing to 8)
- Created /usr/src/app/data directory (fixes FileNotFoundError)
- Created data/ directory for position persistence

SELL LOGIC (already coded in trading_strategy.py):
- +6% profit → AUTO SELL (take profit)
- -2% loss → AUTO SELL (stop loss)
- Trailing stops → Lock in 98% of gains
- Opposite signals → Exit position

CURRENT STATE:
- Balance: \$57.54 USDC (Consumer wallet)
- Holding: 10 positions (will reduce to 8 as profitable sells execute)
- Max positions: 8 (new limit enforced)
- Bot will manage existing positions using profit-based logic

STRATEGY:
Bot will NOT emergency liquidate. Instead it will:
1. Load existing 10 positions from open_positions.json
2. Monitor every 2.5 minutes for profitable exits
3. Sell positions when +6% profit is reached
4. Stop out at -2% if needed
5. Trail stops to lock in gains
6. Won't open new positions until count ≤ 8

Added scripts:
- START_WITH_SELL_LOGIC.sh: Fix + start with sell logic
- EMERGENCY_START.sh: Emergency fix and start
- START_NOW.sh: Quick start with env loading
- FIND_AND_FIX_NOW.py: Balance diagnostic
- Multiple helper scripts for diagnostics"

# Step 4: Push to GitHub
git push origin main

echo ""
echo "✅ Changes committed and pushed!"
echo ""
echo "Now starting bot to apply sell logic to your 10 positions..."
echo ""

# Step 5: Start bot
export $(grep -v '^#' .env | xargs 2>/dev/null || true)
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

exec ./start.sh
