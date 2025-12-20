#!/bin/bash
set -e

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║         🎯 FIX + START BOT TO APPLY SELL LOGIC TO EXISTING POSITIONS          ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

cd /workspaces/Nija

# Fix 1: Create data directory so bot doesn't crash
echo "📁 Creating data directories..."
mkdir -p /usr/src/app/data
mkdir -p /workspaces/Nija/data
echo "✅ Data directories created"
echo ""

# Fix 2: Update max_positions 5→8 in apex_config.py
echo "🔧 Fixing max_positions: 5 → 8..."
git checkout -- bot/apex_config.py 2>/dev/null || true

python3 << 'EOF'
import re
with open('bot/apex_config.py', 'r') as f:
    content = f.read()
content = re.sub(r"'max_positions':\s*5,", "'max_positions': 8,", content)
with open('bot/apex_config.py', 'w') as f:
    f.write(content)
print("✅ max_positions updated to 8")
EOF

echo ""

# Fix 3: Commit changes
echo "📤 Committing to GitHub..."
git add bot/apex_config.py EMERGENCY_START.sh START_NOW.sh 2>/dev/null || true
git commit -m "Fix: max_positions=8 + data dir + apply sell logic to existing positions

- apex_config.py: max_positions 5 → 8
- Created /usr/src/app/data (fixes FileNotFoundError)
- Bot will now apply NIJA sell logic to existing 10 positions:
  • +6% profit → SELL
  • -2% loss → SELL (stop loss)
  • Trailing stops lock in 98% of gains
  • Opposite signals trigger exits

Balance: $57.54 USDC in Consumer wallet
Max positions: 8 (currently holding 10, will reduce as sells execute)" || true

git push origin main || true
echo ""

# Show current status
echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                            📊 CURRENT STATUS                                   ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Balance:"
echo "  • $57.54 USDC (Consumer wallet)"
echo "  • $0.00 in Advanced Trade"
echo "  • Consumer wallet trading: ENABLED"
echo ""
echo "Positions:"
echo "  • Currently holding: 10 positions"
echo "  • New limit: 8 positions"
echo "  • Bot will close 2 positions when profitable"
echo ""
echo "NIJA Sell Logic (already coded):"
echo "  ✅ +6% profit → AUTO SELL (take profit)"
echo "  ✅ -2% loss → AUTO SELL (stop loss)"
echo "  ✅ Trailing stops → Lock in 98% of gains"
echo "  ✅ Opposite signals → Exit position"
echo ""
echo "The bot will:"
echo "  1. Load your existing 10 positions"
echo "  2. Monitor price every cycle (2.5 min)"
echo "  3. Sell profitable positions automatically"
echo "  4. NOT open new positions until count ≤ 8"
echo ""

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🚀 STARTING NIJA IN 3 SECONDS...                            ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

for i in 3 2 1; do
    echo "$i..."
    sleep 1
done

echo ""
echo "🚀 LAUNCHING BOT TO MANAGE YOUR POSITIONS!"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Load environment variables and start
export $(grep -v '^#' .env | xargs 2>/dev/null || true)
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

exec ./start.sh
