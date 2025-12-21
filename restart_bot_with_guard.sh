#!/bin/bash
# Restart bot with new capital guard

echo "=================================================="
echo "🔄 RESTARTING NIJA BOT WITH CAPITAL GUARD = $5.00"
echo "=================================================="
echo ""

# Kill any existing process
echo "1️⃣  Stopping any existing bot process..."
pkill -f "python.*bot.py" 2>/dev/null || true
pkill -f "python.*trading_strategy" 2>/dev/null || true
sleep 2

# Verify Python
echo "2️⃣  Verifying Python environment..."
if [ -x ./.venv/bin/python ]; then
    PY="./.venv/bin/python"
    echo "   ✅ Using venv Python: $($PY --version)"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
    echo "   ✅ Using system Python: $($PY --version)"
else
    echo "   ❌ No Python found"
    exit 1
fi

# Show guard settings
echo "3️⃣  Capital guard settings:"
$PY verify_capital_guard.py

echo ""
echo "4️⃣  Starting bot..."
echo "    Current balance: \$5.05"
echo "    Minimum capital: \$5.00"
echo "    Expected: Trading should resume immediately"
echo ""

# Start bot
export MINIMUM_VIABLE_CAPITAL=5.0
nohup $PY bot.py > nija_output.log 2>&1 &
BOT_PID=$!

echo "✅ Bot started (PID: $BOT_PID)"
echo ""
echo "5️⃣  Monitoring for signals..."
sleep 5

# Show first 20 lines of new output
echo ""
echo "Latest bot output:"
tail -20 nija_output.log

echo ""
echo "=================================================="
echo "🤖 Bot should now be trading with:"
echo "   • Capital guard: \$5.00"
echo "   • Account balance: \$5.05"
echo "   • Position limit: 8 concurrent"
echo "   • Stop-loss: 1.5%"
echo "   • Monitoring: nija_output.log (tail -f)"
echo "=================================================="
