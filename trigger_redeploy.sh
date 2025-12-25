#!/bin/bash
# Force redeploy trigger

git add .redeploy_trigger
git commit -m "REDEPLOY: Funds moved to Advanced Trade - ready for trading"
git push origin main

echo ""
echo "✅ Redeploy triggered!"
echo ""
echo "Your bot will restart with:"
echo "  - Updated balance calculation (Advanced Trade only)"
echo "  - Better diagnostic logging"
echo "  - Funds now accessible for trading"
echo ""
echo "Monitor logs to see trades execute!"
