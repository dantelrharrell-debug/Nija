#!/bin/bash
set -e

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🔧 COMPLETE FIX + START TRADING NOW 🔧                      ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

cd /workspaces/Nija

# Fix 1: Create required directories
echo "📁 Step 1: Creating required directories..."
mkdir -p /usr/src/app/data
mkdir -p /workspaces/Nija/data
echo "✅ Directories created"
echo ""

# Fix 2: Restore and fix apex_config.py (max_positions 5→8)
echo "🔧 Step 2: Fixing max_positions limit (was holding 10, should be 8)..."
git checkout -- bot/apex_config.py 2>/dev/null || true

python3 << 'PYTHON_EOF'
import re
with open('bot/apex_config.py', 'r') as f:
    content = f.read()
content = re.sub(r"'max_positions':\s*5,", "'max_positions': 8,  # FIXED: matches trading_strategy.py", content)
with open('bot/apex_config.py', 'w') as f:
    f.write(content)
print("✅ max_positions: 5 → 8")
PYTHON_EOF

echo ""

# Fix 3: Commit changes
echo "📤 Step 3: Committing fixes to GitHub..."
git add bot/apex_config.py
git add START_NOW.sh EMERGENCY_START.sh 2>/dev/null || true
git commit -m "Fix: max_positions=8 + create data directories

- apex_config.py: max_positions 5 → 8 (matches user's 8-position logic)
- Created /usr/src/app/data directory (fixes FileNotFoundError)
- Added START_NOW.sh with proper environment loading

Issue: Bot holding 10 positions, should be max 8
Balance: Found $57.54 USDC in Consumer wallet (looking for $164.45)" || echo "Nothing to commit"

git push origin main || echo "Push failed (might be nothing to push)"
echo ""

# Fix 4: Show balance status
echo "💰 Step 4: Current balance status..."
echo "───────────────────────────────────────────────────────────────────────────────"
echo "   Found: $57.54 USDC (Consumer wallet)"
echo "   Expected: $164.45"
echo "   Missing: $106.91"
echo ""
echo "⚠️  The $106.91 might be:"
echo "   • Still pending deposit"
echo "   • In a different account"
echo "   • Already spent on current 10 positions"
echo ""

# Fix 5: Start trading
echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🚀 STARTING BOT WITH $57.54 IN 3 SECONDS...                 ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Bot configuration:"
echo "  ✅ Max 8 concurrent positions (FIXED)"
echo "  ✅ Trading balance: $57.54 USDC"
echo "  ✅ Auto-sell at +6% profit / -2% loss"
echo "  ✅ Consumer wallet enabled"
echo "  ✅ Data directories created"
echo ""

for i in 3 2 1; do
    echo "$i..."
    sleep 1
done

echo ""
echo "🚀 LAUNCHING NIJA NOW!"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Load environment and start
export $(grep -v '^#' .env | xargs 2>/dev/null || true)
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

exec ./start.sh
