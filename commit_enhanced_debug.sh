#!/bin/bash
cd /workspaces/Nija

git add bot/broker_manager.py

git commit -m "Add enhanced API debugging to diagnose balance detection issue

- Enhanced v3 API logging to show ALL accounts returned by API
- Log account UUID, type, name, and currency for debugging  
- Better error handling with full traceback on API failures
- Will reveal why API returns zero balances despite funds existing"

git push origin main

echo ""
echo "✅ Enhanced logging committed and pushed to GitHub"
echo ""
echo "🚀 NEXT STEPS:"
echo "   1. Go to Render dashboard"
echo "   2. Click 'Manual Deploy' → 'Clear build cache & deploy'"
echo "   3. Watch the STARTUP logs (first 30 lines after deploy)"
echo "   4. Look for '📁 v3 Advanced Trade API: X account(s)'"
echo "   5. Check if it shows 0 accounts or lists your accounts"
echo ""
