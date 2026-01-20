#!/bin/bash
#
# NIJA Hard Restart Script
# January 20, 2026 - System Cleanup
#
# This script performs a clean restart of NIJA after system optimization
#

set -e  # Exit on error

echo "========================================================================"
echo "  NIJA HARD RESTART - System Cleanup January 20, 2026"
echo "========================================================================"
echo ""

# Step 1: Stop all existing bot processes
echo "Step 1: Stopping existing bot processes..."
pkill -f "python.*bot.py" 2>/dev/null || echo "  No bot.py processes running"
pkill -f "python.*main.py" 2>/dev/null || echo "  No main.py processes running"
pkill -f "python.*trading_strategy.py" 2>/dev/null || echo "  No trading_strategy.py processes running"
sleep 2
echo "  ✓ All bot processes stopped"
echo ""

# Step 2: Verify environment
echo "Step 2: Verifying environment..."
if [ ! -f ".env" ]; then
    echo "  ⚠️  WARNING: .env file not found!"
    echo "  Copy .env.example to .env and configure credentials"
    exit 1
fi
echo "  ✓ Environment file exists"
echo ""

# Step 3: Verify dependencies
echo "Step 3: Verifying dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "  ❌ ERROR: Python 3 not found!"
    exit 1
fi
echo "  ✓ Python 3 found: $(python3 --version)"
echo ""

# Step 4: Display cleanup summary
echo "Step 4: System cleanup applied..."
echo "  ✓ XRP-USD blacklist removed (trade all pairs)"
echo "  ✓ Losing position hold: 3min → 30min"
echo "  ✓ Winning position hold: 8h → 24h"
echo "  ✓ Market scanning: 15 → 30 markets/cycle"
echo "  ✓ Zombie detection: 1h → 24h"
echo "  ✓ Coinbase min balance: \$25 → \$10"
echo ""

# Step 5: Start the bot
echo "Step 5: Starting NIJA..."
echo "  Using start script: ./start.sh"
echo ""

# Check if start.sh exists
if [ ! -f "start.sh" ]; then
    echo "  ⚠️  start.sh not found, using direct Python execution"
    echo "  Starting bot.py..."
    nohup python3 bot.py > logs/nija.log 2>&1 &
    BOT_PID=$!
    echo "  ✓ Bot started with PID: $BOT_PID"
else
    # Run the standard start script
    ./start.sh
    echo "  ✓ Bot started via start.sh"
fi

echo ""
echo "========================================================================"
echo "  ✅ NIJA RESTART COMPLETE"
echo "========================================================================"
echo ""
echo "Next steps:"
echo "  1. Monitor logs: tail -f logs/nija.log"
echo "  2. Check status: python3 check_trading_status.py"
echo "  3. Verify trading: python3 display_broker_status.py"
echo ""
echo "Expected behavior:"
echo "  - Scanning 30 markets per cycle (was 15)"
echo "  - Positions held 30 minutes if losing (was 3 min)"
echo "  - Positions held 24 hours max (was 8 hours)"
echo "  - All 732 pairs tradable (XRP no longer blocked)"
echo ""
echo "See SYSTEM_CLEANUP_JAN_20_2026.md for full details"
echo ""
