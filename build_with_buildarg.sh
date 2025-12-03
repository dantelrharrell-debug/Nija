#!/usr/bin/env bash
set -euo pipefail
# build_with_buildarg.sh
# Build the Docker image using --build-arg GITHUB_TOKEN (insecure: token may appear in build logs/image history).
# Use this only if you cannot commit vendor and your builder does not support BuildKit secrets.
#
# Usage:
#   ./build_with_buildarg.sh --token "ghp_xxx" --target prod --tag nija:prod
#   or set env GITHUB_TOKEN and run:
#   ./build_with_buildarg.sh --target prod --tag nija:prod
#
# WARNING: Passing a token this way is less secure. Revoke the token after use:
#   https://github.com/settings/tokens (Developer settings -> Personal access tokens)

print_help() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --token TOKEN      Provide GitHub PAT on the command line (insecure; will be passed to docker build).
  --target TARGET    Docker build target (default: prod).
  --tag IMAGE_TAG    Docker image tag (default: nija:prod).
  -h,--help          Show this help.
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
  echo "ERROR: Dockerfile not found in $(pwd). Run from repo root."
  exit 1
fi

# Print a redacted build command (do not print the actual token)
echo "Running insecure build using --build-arg (token will be passed to docker build)."
echo "WARNING: This may expose your token in build logs or image layers. Revoke the PAT after use:"
echo "  https://github.com/settings/tokens"

BUILD_CMD=(docker build --progress=plain --build-arg GITHUB_TOKEN="${TOKEN}" --target "${TARGET}" -t "${TAG}" .)

# Print command with token redacted
REDACTED=("${BUILD_CMD[@]}")
for i in "${!REDACTED[@]}"; do
  if [ "${REDACTED[$i]}" = "$TOKEN" ]; then
    REDACTED[$i]="<REDACTED_TOKEN>"
  fi
done
printf 'Executing: '; printf '%q ' "${REDACTED[@]}"; echo

# Run build
"${BUILD_CMD[@]}"

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
  echo "docker build failed with exit code $EXIT_CODE"
  exit $EXIT_CODE
fi

echo "Build completed: ${TAG}"
echo "IMPORTANT: Revoke the token used immediately if it was a long-lived PAT:"
echo "  https://github.com/settings/tokens"
