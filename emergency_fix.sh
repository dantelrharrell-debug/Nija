#!/bin/bash
# EMERGENCY FIX: Sync positions and restart bot
# This fixes the critical "0 positions" bug

echo ""
echo "========================================================================"
echo "🚨 NIJA EMERGENCY FIX - POSITION SYNC & RESTART"
echo "========================================================================"
echo ""

# Step 1: Kill any running bot processes
echo "1️⃣  Stopping any running bot processes..."
pkill -f "python.*bot\.py" 2>/dev/null && echo "   ✅ Stopped running bot" || echo "   ℹ️  No bot process found"
sleep 2

# Step 2: Run emergency position sync
echo ""
echo "2️⃣  Syncing positions from Coinbase..."
python3 emergency_sync_positions.py
SYNC_EXIT=$?

if [ $SYNC_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Position sync failed! Check credentials and try manually:"
    echo "   python3 emergency_sync_positions.py"
    exit 1
fi

# Step 3: Verify position file was created
echo ""
echo "3️⃣  Verifying position file..."
if [ ! -f "data/open_positions.json" ]; then
    echo "   ❌ Position file not created!"
    exit 1
fi

POSITION_COUNT=$(python3 -c "import json; data=json.load(open('data/open_positions.json')); print(data.get('count', 0))")
echo "   ✅ Found $POSITION_COUNT positions in file"

# Step 4: Restart bot
echo ""
echo "4️⃣  Starting bot..."
echo "   Using: bash start.sh"
echo ""
echo "========================================================================"
echo ""

bash start.sh

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Bot started successfully!"
else
    echo "❌ Bot startup failed (exit code: $EXIT_CODE)"
    echo ""
    echo "Check the error above. Common issues:"
    echo "  - Missing .env file or credentials"
    echo "  - Python dependencies not installed"
    echo "  - Port already in use"
    echo ""
    echo "Try running manually:"
    echo "  bash start.sh"
    echo ""
    echo "Or check the log:"
    echo "  tail -50 nija.log"
fi

exit $EXIT_CODE
