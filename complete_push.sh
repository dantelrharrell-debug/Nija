#!/bin/bash
# Complete the commit and push
cd /workspaces/Nija

echo "🔧 Fixing git push..."
echo ""

# Check current status
echo "Current git status:"
git status --short

echo ""
echo "Attempting to push..."
git push origin main 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ SUCCESS! All changes pushed to GitHub"
else
    echo ""
    echo "❌ Push failed with exit code: $EXIT_CODE"
    echo ""
    echo "Trying to add and commit everything..."
    git add -A
    git commit -m "Add profit fix tools and documentation" 2>&1
    git push origin main 2>&1
fi
