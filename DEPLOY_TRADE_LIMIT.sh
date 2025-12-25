#!/bin/bash
# Deploy consecutive trade limit fix

echo "=================================="
echo "🚀 DEPLOYING 8-TRADE LIMIT FIX"
echo "=================================="
echo ""
echo "This adds:"
echo "  - Max 8 consecutive BUY trades"
echo "  - Forces sell cycle after 8 buys"
echo "  - Resets counter when positions close"
echo "  - Prevents overtrading in one direction"
echo ""

cd /workspaces/Nija

echo "📝 Adding files..."
git add bot/trading_strategy.py monitor_selling.py

echo "💾 Committing..."
git commit -m "🔧 Add 8 consecutive trade limit to prevent overtrading

FEATURE: Prevent buying after 8 consecutive trades until positions are sold

LOGIC:
- Track consecutive_trades counter (increments on each BUY)
- Block new BUY signals after reaching 8 consecutive trades
- Reset counter to 0 when positions close (SELL)
- Forces bot to sell existing positions before buying more

BENEFITS:
- Prevents capital lockup in one direction
- Ensures regular profit-taking cycles
- Balances buy/sell ratio
- Reduces risk of holding too many positions

FILES:
- bot/trading_strategy.py: Added consecutive trade tracking
- monitor_selling.py: Real-time sell monitoring script

MONITORING:
Run: python3 monitor_selling.py
Shows live BUY/SELL ratio and alerts on new sells"

echo "🚀 Pushing to GitHub..."
git push origin main

echo ""
echo "=================================="
echo "✅ DEPLOYED!"
echo "=================================="
echo ""
echo "Bot will now:"
echo "  1. Buy up to 8 consecutive trades"
echo "  2. STOP buying and wait for sells"
echo "  3. Reset counter when positions close"
echo "  4. Resume buying after sell cycle"
echo ""
echo "Monitor with: python3 monitor_selling.py"
echo "=================================="
