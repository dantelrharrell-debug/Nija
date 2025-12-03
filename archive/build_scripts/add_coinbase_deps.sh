#!/usr/bin/env bash
set -euo pipefail

# branch name & commit message
BRANCH="safe/tradingview-webhook"
COMMIT_MSG="Add coinbase-advanced and crypto deps for Coinbase Advanced + ES256 support"

echo "Creating branch $BRANCH..."
git checkout -b "$BRANCH"

echo "Appending dependencies to bot/requirements.txt and web/requirements.txt..."
printf "\nPyJWT[crypto]>=2.6.0\ncryptography>=40.0.0\necdsa>=0.18.0\ncoinbase-advanced>=0.1.0\n" >> bot/requirements.txt
printf "\nPyJWT[crypto]>=2.6.0\ncryptography>=40.0.0\necdsa>=0.18.0\ncoinbase-advanced>=0.1.0\n" >> web/requirements.txt

echo "Staging files..."
git add bot/requirements.txt web/requirements.txt

echo "Committing..."
git commit -m "$COMMIT_MSG"

echo "Pushing branch to origin..."
git push -u origin "$BRANCH"

echo "Done. Branch pushed: $BRANCH"
echo "Next: open PR and trigger your CI/deploy or redeploy from Render/Railway."
