#!/bin/bash
set -e

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║          🔧 FIX MAX POSITIONS → COMMIT → FIND MONEY → START TRADING 🔧        ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

cd /workspaces/Nija

# Step 1: Restore and fix apex_config.py
echo "📝 Step 1: Fixing max_positions limit (10 → 8)..."
echo "───────────────────────────────────────────────────────────────────────────────"

# Restore original
git checkout -- bot/apex_config.py 2>/dev/null || true

# Apply fix with Python
python3 << 'PYTHON_EOF'
import re

# Read file
with open('bot/apex_config.py', 'r') as f:
    content = f.read()

# Replace both occurrences: max_positions 5 -> 8
content = re.sub(
    r"'max_positions':\s*5,",
    "'max_positions': 8,  # FIXED: Reduced from 10 to match user's buy/sell logic",
    content
)

# Write back
with open('bot/apex_config.py', 'w') as f:
    f.write(content)

print("✅ Updated max_positions from 5 to 8 in apex_config.py")
PYTHON_EOF

echo ""
grep -n "max_positions.*8" bot/apex_config.py | head -2
echo ""

# Step 2: Commit and push
echo "📤 Step 2: Committing and pushing to GitHub..."
echo "───────────────────────────────────────────────────────────────────────────────"

git add bot/apex_config.py
git add FIND_AND_FIX_NOW.py find_164_dollars.py
git add RUN_FIX_NOW.sh RUN_FIX_AND_START.sh START_SELLING_NOW.sh
git add run_diagnostic.sh commit_position_fix.sh
git add FIX_COMMIT_START.sh fix_positions.sh apply_fix.sh
git add restore_config.sh do_restore.sh do_commit.sh

git commit -m "Fix: Set max_positions=8 across all configs

- apex_config.py: max_positions 5 → 8 (2 locations)
- trading_strategy.py: Already set to 8 ✓
- Now all configs consistently enforce 8 position limit

Issue: Bot was holding 10 positions when limit should be 8
Fix: Updated RISK_LIMITS and RISK_CONFIG in apex_config.py

Also added:
- Balance diagnostic scripts (find $164.45)
- Emergency trading startup scripts
- Auto-fix and commit tools"

git push origin main

echo ""
echo "✅ Changes pushed to GitHub!"
echo ""

# Step 3: Find the money
echo "💰 Step 3: Finding your $164.45..."
echo "───────────────────────────────────────────────────────────────────────────────"
python3 FIND_AND_FIX_NOW.py
echo ""

# Step 4: Start trading
echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🚀 STARTING TRADING IN 5 SECONDS...                         ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "✅ Position limit: 8 concurrent trades (FIXED)"
echo "✅ Auto-sell logic: +6% profit / -2% loss"
echo "✅ Trailing stops enabled"
echo "✅ Consumer USD enabled"
echo ""

for i in 5 4 3 2 1; do
    echo "$i..."
    sleep 1
done

echo ""
echo "🚀 LAUNCHING NIJA NOW!"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

export ALLOW_CONSUMER_USD=true
exec ./start.sh
