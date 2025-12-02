#!/usr/bin/env bash
set -euo pipefail
echo "=== Railway build script started ==="

# directory we will use for working
WORKDIR="/tmp/railway_build"
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"

# 1) upgrade pip and install normal requirements
python -m pip install --upgrade pip setuptools wheel
if [ -f requirements.txt ]; then
  pip install --no-cache-dir -r requirements.txt
else
  echo "No requirements.txt found — skipping pip install -r requirements.txt"
fi

# 2) install private repo using PAT stored in $GITHUB_PAT (Railway variable)
if [ -z "${GITHUB_PAT:-}" ]; then
  echo "GITHUB_PAT not set — skipping private repo install"
else
  echo "Installing private repo coinbase_advanced_py from GitHub using GITHUB_PAT..."
  # clone shallow; install; then remove
  git -c http.extraHeader="AUTHORIZATION: basic ${GITHUB_PAT}" clone --depth 1 https://github.com/dantelrharrell-debug/coinbase_advanced_py.git "$WORKDIR/coinbase_advanced_py" || {
    # Fallback: use URL-embedded PAT (less secure, but sometimes required in CI)
    echo "Primary git clone failed, attempting URL-embedded clone as fallback..."
    git clone --depth 1 "https://${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git" "$WORKDIR/coinbase_advanced_py"
  }

  if [ -d "$WORKDIR/coinbase_advanced_py" ]; then
    pip install --no-cache-dir "$WORKDIR/coinbase_advanced_py"
    rm -rf "$WORKDIR/coinbase_advanced_py"
  else
    echo "Failed to clone coinbase_advanced_py — continuing without it."
  fi
fi

echo "=== Railway build script finished ==="
