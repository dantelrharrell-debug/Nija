#!/bin/bash
echo "Last commit:"
git log -1 --oneline
echo ""
echo "What changed in last commit:"
git diff-tree --no-commit-id --name-only -r HEAD
echo ""
echo "Check if bot files are in git:"
echo ""
echo "bot.py line 59 in git:"
git show HEAD:bot.py 2>/dev/null | sed -n '59p' || echo "FILE NOT IN LAST COMMIT"
echo ""
echo "Second to last commit:"
git log -2 --oneline | tail -1
echo ""
echo "What changed 2 commits ago:"
git diff-tree --no-commit-id --name-only -r HEAD~1
