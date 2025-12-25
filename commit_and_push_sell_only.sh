#!/bin/bash
set -e

cd /workspaces/Nija

# Ensure git identity (override if needed)
if ! git config user.email >/dev/null; then
  git config user.email "dantelrharrell@users.noreply.github.com"
fi
if ! git config user.name >/dev/null; then
  git config user.name "dantelrharrell-debug"
fi
git config commit.gpgsign false

echo "🔧 Staging changes..."
# Stage targeted files explicitly to avoid accidental noise
git add bot/trading_strategy.py TRADING_EMERGENCY_STOP.conf COMMIT_MESSAGE_SELL_ONLY_MODE.txt emergency_liquidate.py || true

# Fallback: if nothing staged, try all
if git diff --cached --quiet; then
  git add -A
fi

if git diff --cached --quiet; then
  echo "⚠️  Nothing to commit. Aborting."
  exit 0
fi

echo "📝 Committing with prepared message..."
if [ -f COMMIT_MESSAGE_SELL_ONLY_MODE.txt ]; then
  git commit -F COMMIT_MESSAGE_SELL_ONLY_MODE.txt
else
  git commit -m "Enable SELL-ONLY mode via TRADING_EMERGENCY_STOP.conf; keep auto-exits; no sells observed yet"
fi

echo "🚀 Pushing to origin main..."
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "⚠️  Not on main (current: $CURRENT_BRANCH). Pushing to current branch."
  git push -u origin "$CURRENT_BRANCH"
else
  git push origin main
fi

echo "✅ Done." 
