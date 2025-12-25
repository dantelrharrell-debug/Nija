#!/usr/bin/env bash
set -euo pipefail

# Pull latest remote changes with rebase, then push
# Use when remote is ahead and push is rejected (non-fast-forward)

branch="main"
remote="origin"

echo "🔄 Pulling with rebase from $remote/$branch ..."
git pull --rebase "$remote" "$branch"

echo "🚀 Pushing local commits to $remote/$branch ..."
git push "$remote" "$branch"

echo "✅ Push complete. Railway should auto-deploy shortly."