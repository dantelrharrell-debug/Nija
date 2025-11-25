#!/usr/bin/env bash
set -euo pipefail

echo ">>> 1) Fetch + rebase onto origin/main"
git fetch origin
# rebase local main on remote main
git checkout main
git pull --rebase origin main

echo ">>> 2) Clean potential broken submodule entries (safe)"
# remove any leftover submodule working-tree path and gitmodules entries
if [ -f .gitmodules ]; then
  echo "Found .gitmodules — removing entries for coinbase-advanced if present"
  git config -f .gitmodules --get-regexp path || true
  # If coinbase-advanced path exists, remove it from git index and .gitmodules
  if git ls-files --error-unmatch coinbase-advanced > /dev/null 2>&1; then
    git rm -f coinbase-advanced || true
  fi

  # Remove any section in .gitmodules that references coinbase-advanced
  if grep -q "coinbase-advanced" .gitmodules 2>/dev/null; then
    awk 'BEGIN{out=1} /coinbase-advanced/{out=0} out{print $0}' .gitmodules > .gitmodules.tmp || true
    mv .gitmodules.tmp .gitmodules
    git add .gitmodules || true
    git commit -m "Remove coinbase-advanced submodule entry from .gitmodules (cleanup)" || true
  fi
else
  echo "No .gitmodules file found."
fi

# Remove git internals for submodule if present
if [ -d .git/modules/coinbase-advanced ]; then
  echo "Removing .git/modules/coinbase-advanced"
  rm -rf .git/modules/coinbase-advanced
fi

# Final commit (if anything staged)
if ! git diff --cached --quiet; then
  git commit -m "Cleanup submodule metadata (coinbase-advanced)" || true
fi

echo ">>> 3) Push cleaned main to origin"
git push origin main

echo ">>> Done. Local main is rebased on origin/main and broken submodule metadata removed (if present)."
