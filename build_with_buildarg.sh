#!/usr/bin/env bash
set -euo pipefail

# build_with_buildarg.sh
# Insecure fallback: passes GITHUB_TOKEN as --build-arg to docker build (token may appear in logs/history).
# Use only if you cannot commit vendor and your remote builder does not support BuildKit secrets.
#
# Usage:
#   ./build_with_buildarg.sh --token "ghp_xxx" --target prod --tag nija:prod
#   or: GITHUB_TOKEN="ghp_xxx" ./build_with_buildarg.sh --target prod --tag nija:prod
#
# WARNING: Passing a token this way is less secure. Revoke the PAT after use:
#   https://github.com/settings/tokens

print_help() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --token TOKEN      Provide GitHub PAT (optional if GITHUB_TOKEN env var set).
  --target TARGET    Docker build target (default: prod).
  --tag IMAGE_TAG    Docker image tag (default: nija:prod).
  -h, --help         Show this help.
EOF
}

TOKEN="${GITHUB_TOKEN:-}"
TARGET="prod"
TAG="nija:prod"

# parse args
while [ $# -gt 0 ]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2;;
    --target) TARGET="$2"; shift 2;;
    --tag) TAG="$2"; shift 2;;
    -h|--help) print_help; exit 0;;
    *) echo "Unknown arg: $1"; print_help; exit 2;;
  esac
done

if [ -z "$TOKEN" ]; then
  echo "ERROR: No token provided. Use --token or set GITHUB_TOKEN env var."
  exit 1
fi

if [ ! -f Dockerfile ]; then
  echo "ERROR: Dockerfile not found in $(pwd). Run from repository root."
  exit 1
fi

echo "Running insecure build using --build-arg (token will be passed to docker build)."
echo "WARNING: This may expose your token in build logs or image layers. Revoke the PAT immediately after use:"
echo "  https://github.com/settings/tokens"

# Run the build (token value is not printed)
docker build --progress=plain --build-arg GITHUB_TOKEN="${TOKEN}" --target "${TARGET}" -t "${TAG}" .

BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
  echo "docker build failed with exit code $BUILD_EXIT"
  exit $BUILD_EXIT
fi

echo "Build completed: ${TAG}"
echo "IMPORTANT: Revoke the token used immediately in GitHub settings:"
echo "  https://github.com/settings/tokens"
