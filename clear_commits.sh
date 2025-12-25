#!/bin/bash
# Clear any pending commits
git reset HEAD~1 2>/dev/null || true
git restore --staged . 2>/dev/null || true
echo "✅ Commits cleared"
git status
