#!/bin/bash
cd /workspaces/Nija
git commit -F .git/COMMIT_EDITMSG
git push origin main
echo ""
echo "✅ Changes committed and pushed!"
echo ""
echo "Next: Run python3 verify_balance_now.py to check your balance"
