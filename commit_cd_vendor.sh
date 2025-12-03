#!/usr/bin/env bash
set -euo pipefail
# commit_cd_vendor.sh
# Add, commit (if needed), and push cd/vendor/coinbase_advanced_py into the current git repo.
# Usage: run from your repository root.

VENDOR_PATH="cd/vendor/coinbase_advanced_py"
COMMIT_MSG="Add vendor/coinbase_advanced_py for Docker build"

if [ ! -d "$VENDOR_PATH" ]; then
  echo "ERROR: Vendor folder not found at: $VENDOR_PATH"
  exit 1
fi

echo "Staging $VENDOR_PATH..."
git add "$VENDOR_PATH"

# If there are staged changes, commit and push. Otherwise inform the user.
if ! git diff --staged --quiet; then
  echo "Committing staged changes..."
  git commit -m "$COMMIT_MSG"
  echo "Pushing to origin $(git rev-parse --abbrev-ref HEAD)..."
  git push
  echo "Vendor folder committed and pushed."
else
  echo "No changes to commit for $VENDOR_PATH."
fi
