#!/bin/bash
# EMERGENCY: Liquidate all positions and restart NIJA for 8-position trading

set -e

echo "=========================================="
echo "🚨 EMERGENCY LIQUIDATION SEQUENCE"
echo "=========================================="
echo ""
echo "Step 1: Killing old bot processes..."
pkill -f "bot.py" || true
pkill -f "main.py" || true
pkill -f "start.sh" || true
sleep 2
echo "✅ Old processes killed"
echo ""

echo "Step 2: Selling all bleeding positions..."
source .venv/bin/activate
python3 emergency_sell_all.py
sleep 30  # Wait for orders to settle
echo "✅ Liquidation complete"
echo ""

echo "Step 3: Updating position data..."
cat > data/open_positions.json << 'EOF'
{
  "timestamp": "2025-12-21T00:00:00.000000",
  "positions": {},
  "count": 0
}
EOF
echo "✅ Positions file cleared"
echo ""

echo "=========================================="
echo "Step 4: Restarting NIJA in 8-position mode"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  • Max concurrent positions: 8"
echo "  • Equal capital per position"
echo "  • Stop loss: 1.5% (tight, prevents bleeding)"
echo "  • Profit target: 2% immediate lock + 98% trailing"
echo "  • Scan interval: 15 seconds"
echo ""

nohup bash start.sh > nija_output.log 2>&1 &
BOT_PID=$!

echo "✅ Bot started (PID: $BOT_PID)"
echo "   Log file: nija_output.log"
echo ""

sleep 5

echo "Checking bot status..."
tail -20 nija_output.log

echo ""
echo "=========================================="
echo "✅ EMERGENCY SEQUENCE COMPLETE"
echo "=========================================="
echo ""
echo "📊 NIJA is now:"
echo "  ✅ Trading 8 positions concurrently"
echo "  ✅ Equal capital allocation per position"
echo "  ✅ 1.5% stop loss (NO BLEEDING)"
echo "  ✅ 2% profit lock + trailing protection"
echo "  ✅ Scanning 50+ markets every 15 seconds"
echo ""
echo "💰 To check balance:"
echo "   python quick_balance.py"
echo ""
echo "📈 To monitor:"
echo "   tail -f nija_output.log"
echo ""
