#!/usr/bin/env bash
set -euo pipefail

# commit_cd_vendor.sh
# Usage: run this from the repository root to add and push cd/vendor/coinbase_advanced_py.
VENDOR_PATH="cd/vendor/coinbase_advanced_py"
COMMIT_MSG="Add vendor/coinbase_advanced_py for Docker build"

if [ ! -d "$VENDOR_PATH" ]; then
  echo "ERROR: Vendor folder not present at: $VENDOR_PATH"
  exit 1
fi

echo "Staging $VENDOR_PATH ..."
git add "$VENDOR_PATH"

# Only commit if there are staged changes
if ! git diff --staged --quiet; then
  echo "Committing staged changes..."
  git commit -m "$COMMIT_MSG"
  echo "Pushing branch $(git rev-parse --abbrev-ref HEAD) to origin..."
  git push
  echo "Vendor folder committed and pushed."
else
  echo "No changes detected to commit for $VENDOR_PATH (already committed)."
fi
