#!/bin/bash
# Atomic commit and push for init hardening + rebuild trigger
set -e

cd /workspaces/Nija

echo "========================================"
echo "📊 GIT STATUS BEFORE COMMIT"
echo "========================================"
git status --short

echo ""
echo "========================================"
echo "📤 STAGING ALL CHANGES"
echo "========================================"
git add -A
echo "✅ Staged."

echo ""
echo "========================================"
echo "📝 COMMITTING WITH MESSAGE"
echo "========================================"
git commit -F COMMIT_MESSAGE.txt

echo ""
echo "========================================"
echo "🚀 PUSHING TO GITHUB"
echo "========================================"
git push origin main

echo ""
echo "========================================"
echo "✅ COMMIT & PUSH COMPLETE"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Get Railway service name:"
echo "   railway status"
echo ""
echo "2. Force a no-cache rebuild:"
echo "   railway up --service <your-service-name> --build --no-cache"
echo ""
echo "3. Tail logs to verify:"
echo "   railway logs -f --service <your-service-name>"
echo ""
echo "4. Look for: BUILD SIGNATURE: TradingStrategy v7.1 init-hardened _os alias - 2025-12-24T17:40Z"
echo "========================================"
