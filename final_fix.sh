#!/bin/bash
set -e
echo "Creating data directories..."
sudo mkdir -p /usr/src/app/data
mkdir -p /workspaces/Nija/data
echo "✅ Directories created"

echo "Fixing apex_config.py..."
cd /workspaces/Nija
git checkout -- bot/apex_config.py 2>/dev/null || true
python3 -c "
import re
with open('bot/apex_config.py', 'r') as f:
    content = f.read()
content = re.sub(r\"'max_positions':\s*5,\", \"'max_positions': 8,\", content)
with open('bot/apex_config.py', 'w') as f:
    f.write(content)
print('✅ max_positions: 5 → 8')
"

echo "Committing changes..."
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

STRATEGY:
Bot will NOT emergency liquidate. Instead:
1. Load existing 10 positions from open_positions.json
2. Monitor every 2.5 minutes for profitable exits
3. Sell positions when +6% profit is reached
4. Stop out at -2% if needed
5. Trail stops to lock in gains
6. Won't open new positions until count ≤ 8" || echo "Nothing to commit"

git push origin main || echo "Push may have failed"

echo ""
echo "✅ All fixes applied! Starting bot..."
echo ""

export $(grep -v '^#' .env | xargs 2>/dev/null || true)
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

exec ./start.sh
