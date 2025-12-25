#!/bin/bash
# STOP ALL BOT PROCESSES IMMEDIATELY

echo "========================================"
echo "🛑 STOPPING ALL NIJA BOT PROCESSES"
echo "========================================"
echo ""

# Find and kill Python bot processes
echo "🔍 Finding running bot processes..."
ps aux | grep -E 'python.*(main|bot|trading_strategy|nija)' | grep -v grep

echo ""
echo "🔪 Killing bot processes..."

# Kill by name patterns
pkill -9 -f "python.*main.py" 2>/dev/null
pkill -9 -f "python.*bot.py" 2>/dev/null
pkill -9 -f "trading_strategy" 2>/dev/null

echo ""
echo "✅ Bot processes stopped"
echo ""
echo "========================================"
echo "📊 NEXT STEPS - CHOOSE ONE:"
echo "========================================"
echo ""
echo "❌ OPTION 1: STOP TRADING (Current capital too small)"
echo "   • Portfolio: \$0.00"
echo "   • Coinbase fees: 2-4% per trade"
echo "   • \$5-10 positions lose money even when winning"
echo "   • Save up \$100+ before trading again"
echo ""
echo "✅ OPTION 2: DEPOSIT PROPER CAPITAL"
echo "   • Deposit \$100-200 to Coinbase Advanced Trade"
echo "   • Bot will trade \$20-80 positions"
echo "   • Fees drop to <1% (profitable range)"
echo "   • Strategy can actually work"
echo "   • Then run: python3 main.py"
echo ""
echo "🔄 OPTION 3: SWITCH EXCHANGES"
echo "   • Move to Binance/Kraken (0.1-0.5% fees)"
echo "   • Same strategy, lower costs"
echo "   • Can trade with \$50 capital"
echo ""
echo "========================================"
echo ""
echo "⚠️  CRITICAL: Do NOT deposit \$5-10 amounts!"
echo "   Small deposits will disappear to fees instantly."
echo ""
echo "💡 Bot strategy is CORRECT - problem is fee structure"
echo "   Need minimum \$50-100 to overcome Coinbase fees"
echo ""
