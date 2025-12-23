#!/bin/bash
# Emergency fix deployment script

echo "🚨 EMERGENCY FIX: Deploying restart loop prevention"
echo "=================================================="

# Stage the changes
git add bot/trading_strategy.py data/open_positions.json emergency_position_reset.py data/open_positions_backup_20251223_225454.json

# Commit with detailed message  
git commit -m "EMERGENCY FIX: Prevent restart loop from stale positions

ROOT CAUSE:
- Position tracker had 19 positions with crypto_quantity=0 (ghosts)
- Bot loaded these on startup, detected overage (19 > 7)
- Tried to close positions, crashed before completing
- Restart loop: load 19 ghosts → overage → crash → repeat

SOLUTION:
1. Reset position tracking file (cleared all stale positions)
2. Added stale position cleanup BEFORE overage detection
3. Bot now removes zero-quantity positions immediately
4. Prevents API rate limiting from checking prices for ghosts

CHANGES:
- bot/trading_strategy.py: Clean stale positions in close_excess_positions()
- data/open_positions.json: Reset to empty (bot will resync from Coinbase)
- emergency_position_reset.py: One-time cleanup script (already run)

RESULT:
- Bot will start fresh, sync actual holdings from Coinbase
- No more restart loops
- Proper position tracking going forward"

# Push to Railway
echo ""
echo "📤 Pushing to Railway..."
git push origin main

echo ""
echo "✅ Fix deployed! Bot will restart with clean position tracking."
echo "🔄 Monitor Railway logs to confirm successful startup."
