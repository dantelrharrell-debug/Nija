#!/usr/bin/env bash
# clone_and_build.sh
# - Attempts to obtain the vendor package and build the prod Docker image.
# - Preferred flow: try SSH clone (git@github.com:...), fallback to HTTPS using a PAT read securely.
# - After cloning, removes vendor's .git, stages and optionally commits+pushes the vendor into the repo,
#   then runs docker build --target prod -t nija:prod .
#
# Usage:
#   1) Save this file at your repository root (where Dockerfile is).
#   2) chmod +x clone_and_build.sh
#   3) ./clone_and_build.sh
#
# Notes:
# - The script will NOT print your token to stdout.
# - If SSH cloning fails, the script will prompt for a token (or use GITHUB_TOKEN env var if set).
# - If you approve, the vendor directory will be committed & pushed. If you decline, the vendor will be cloned locally
#   but not committed.
# - If you cannot run docker locally, you can still use the script to place vendor in cd/vendor/... then push the branch;
#   the remote builder will then be able to build without secrets.

set -euo pipefail

VENDOR_DIR="cd/vendor/coinbase_advanced_py"
REPO_SSH="git@github.com:dantelrharrell-debug/coinbase_advanced_py.git"
REPO_HTTPS_BASE="github.com/dantelrharrell-debug/coinbase_advanced_py.git"
COMMIT_MSG="Add vendor/coinbase_advanced_py for Docker build"
DO_BUILD=true

# helper
err() { printf '%s\n' "$@" >&2; }

# ensure running from repo root (Dockerfile present)
if [ ! -f Dockerfile ]; then
  err "ERROR: Dockerfile not found in current directory: $(pwd)"
  err "Run this script from the repository root where your Dockerfile lives."
  exit 1
fi

if [ -d "$VENDOR_DIR" ]; then
  err "ERROR: $VENDOR_DIR already exists. Please remove or move it first if you want to re-clone."
  ls -la "$VENDOR_DIR" || true
  exit 1
fi

# make parent dir
mkdir -p "$(dirname "$VENDOR_DIR")"

echo "Attempting to clone vendor via SSH (preferred)..."
set +e
git clone --depth 1 "$REPO_SSH" "$VENDOR_DIR"
ssh_rc=$?
set -e

if [ $ssh_rc -eq 0 ]; then
  echo "SSH clone succeeded."
else
  echo "SSH clone failed (exit $ssh_rc). Will attempt HTTPS clone using a token."
  # Acquire token: prefer GITHUB_TOKEN env, else prompt
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    TOKEN="$GITHUB_TOKEN"
    token_from_env=1
  else
    token_from_env=0
    printf "Enter GitHub PAT (scopes: repo or public_repo) - input will be hidden: "
    # read -s doesn't work in some environments; but we'll try:
    read -r -s TOKEN || true
    echo ""
    if [ -z "$TOKEN" ]; then
      err "No token entered. Aborting."
      exit 1
    fi
  fi

  # Perform clone using token (do not echo token)
  set +e
  git clone --depth 1 "https://${TOKEN}@${REPO_HTTPS_BASE}" "$VENDOR_DIR"
  clone_rc=$?
  set -e

  # unset token variables ASAP
  if [ "$token_from_env" -eq 1 ]; then
    unset GITHUB_TOKEN || true
  fi
  TOKEN="" || true

  if [ $clone_rc -eq 0 ]; then
    echo "HTTPS clone succeeded."
  else
    err "HTTPS clone failed (exit $clone_rc). Cannot proceed."
    rm -rf "$VENDOR_DIR" || true
    exit 1
  fi
fi

# remove nested .git if present to avoid nested repo issues
if [ -d "$VENDOR_DIR/.git" ]; then
  echo "Removing nested .git inside vendor..."
  rm -rf "$VENDOR_DIR/.git"
fi

echo "Vendor cloned to: $VENDOR_DIR"
ls -la "$VENDOR_DIR" || true

# Stage vendor for commit
git add "$VENDOR_DIR"

if git diff --staged --quiet; then
  echo "No changes staged for commit (vendor may be identical to what's already in the repo)."
  commit_needed=0
else
  commit_needed=1
fi

if [ "$commit_needed" -eq 1 ]; then
  printf "About to commit and push %s. Proceed? [y/N]: " "$VENDOR_DIR"
  read -r CONF
  if [[ "$CONF" =~ ^[Yy]$ ]]; then
    git commit -m "$COMMIT_MSG"
    echo "Pushing branch $(git rev-parse --abbrev-ref HEAD) to origin..."
    git push
    echo "Vendor committed and pushed."
  else
    echo "Commit canceled by user. Vendor is present locally but not committed."
  fi
else
  echo "No commit needed."
fi

# Build prod image if docker available
if command -v docker >/dev/null 2>&1; then
  printf "Docker CLI found. Build prod image now? [Y/n]: "
  read -r DO_ANS
  if [[ "$DO_ANS" =~ ^[Nn]$ ]]; then
    DO_BUILD=false
  fi
else
  echo "Docker CLI not found; skipping local build. You can run the remote builder after pushing vendor."
  DO_BUILD=false
fi

if [ "$DO_BUILD" = true ]; then
  echo "Building prod image: docker build --progress=plain --target prod -t nija:prod ."
  docker build --progress=plain --target prod -t nija:prod .
  build_rc=$?
  if [ $build_rc -eq 0 ]; then
    echo "Build succeeded: nija:prod"
    echo ""
    echo "Quick smoke-test suggestion (web):"
    echo "  docker run --rm -d -e NIJA_SERVICE=web -p 8000:8000 --name nija_test nija:prod"
    echo "  sleep 2 && curl -fsS http://localhost:8000/ || (docker logs nija_test --tail 200 && docker rm -f nija_test && exit 1)"
  else
    err "Build failed with exit code $build_rc. See docker output above for details."
    exit $build_rc
  fi
else
  echo "Build skipped."
fi

echo "Done."
