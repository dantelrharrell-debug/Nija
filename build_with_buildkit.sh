#!/usr/bin/env bash
# build_with_buildkit.sh
# Build the Docker image using BuildKit and a secure secret for GitHub token.
# Usage:
#   ./build_with_buildkit.sh --secret-file /tmp/github_token --target prod --tag nija:prod
#   ./build_with_buildkit.sh --token "$GITHUB_TOKEN" --target prod --tag nija:prod
#   ./build_with_buildkit.sh --prompt --target dev --tag nija:dev
set -euo pipefail

print_help() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --secret-file PATH    Use an existing file containing the GitHub token (preferred).
  --token TOKEN         Provide token value on the command line (temporary file will be created).
  --prompt              Prompt interactively for the token (no echo).
  --target TARGET       Docker build target stage (default: prod).
  --tag IMAGE_TAG       Docker image tag (default: nija:prod for prod, nija:dev for dev).
  --no-cleanup          Keep temporary token file (for debugging).
  -h, --help            Show this help and exit.
EOF
}

SECRET_FILE=""
TOKEN=""
PROMPT=0
TARGET="prod"
TAG=""
NO_CLEANUP=0

# parse args
while [ $# -gt 0 ]; do
  case "$1" in
    --secret-file) SECRET_FILE="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --prompt) PROMPT=1; shift;;
    --target) TARGET="$2"; shift 2;;
    --tag) TAG="$2"; shift 2;;
    --no-cleanup) NO_CLEANUP=1; shift;;
    -h|--help) print_help; exit 0;;
    *) echo "Unknown arg: $1"; print_help; exit 2;;
  esac
done

# infer default tag
if [ -z "$TAG" ]; then
  TAG="nija:${TARGET}"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker CLI not found"
  exit 1
fi

if [ ! -f Dockerfile ]; then
  echo "ERROR: Dockerfile not found in $(pwd)"
  exit 1
fi

TMP_CREATED=0
TMP_PATH=""

cleanup() {
  if [ "$TMP_CREATED" -eq 1 ] && [ "$NO_CLEANUP" -eq 0 ]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u -z "$TMP_PATH" 2>/dev/null || rm -f "$TMP_PATH"
    else
      rm -f "$TMP_PATH"
    fi
  fi
}
trap cleanup EXIT

if [ -n "$SECRET_FILE" ]; then
  if [ ! -f "$SECRET_FILE" ]; then
    echo "ERROR: --secret-file not found: $SECRET_FILE"
    exit 1
  fi
  SECRET_PATH="$SECRET_FILE"
elif [ -n "$TOKEN" ]; then
  TMP_PATH="$(mktemp)"
  printf "%s" "$TOKEN" > "$TMP_PATH"
  chmod 600 "$TMP_PATH"
  TMP_CREATED=1
  SECRET_PATH="$TMP_PATH"
elif [ "$PROMPT" -eq 1 ]; then
  read -r -s -p "GitHub token: " TOKEN
  echo ""
  if [ -z "$TOKEN" ]; then
    echo "ERROR: no token entered"
    exit 1
  fi
  TMP_PATH="$(mktemp)"
  printf "%s" "$TOKEN" > "$TMP_PATH"
  chmod 600 "$TMP_PATH"
  TMP_CREATED=1
  SECRET_PATH="$TMP_PATH"
elif [ -n "${GITHUB_TOKEN:-}" ]; then
  TMP_PATH="$(mktemp)"
  printf "%s" "$GITHUB_TOKEN" > "$TMP_PATH"
  chmod 600 "$TMP_PATH"
  TMP_CREATED=1
  SECRET_PATH="$TMP_PATH"
else
  echo "ERROR: No token provided. Use --secret-file, --token, --prompt, or set GITHUB_TOKEN env var."
  exit 1
fi

echo "Using secret file: $SECRET_PATH"
echo "Docker target: $TARGET"
echo "Image tag: $TAG"

# Run BuildKit-enabled build with secret mounted as /run/secrets/github_token in builder stage
BUILD_CMD=(docker build --progress=plain --secret id=github_token,src="$SECRET_PATH" --target "$TARGET" -t "$TAG" .)

# Print redacted command
REDACTED_CMD=("${BUILD_CMD[@]}")
for i in "${!REDACTED_CMD[@]}"; do
  if [ "${REDACTED_CMD[$i]}" = "$SECRET_PATH" ]; then
    REDACTED_CMD[$i]="<secret_file>"
  fi
done

printf "Running (BuildKit forced): DOCKER_BUILDKIT=1"
for part in "${REDACTED_CMD[@]}"; do
  printf ' %q' "$part"
done
printf "\n\n"

DOCKER_BUILDKIT=1 "${BUILD_CMD[@]}"

echo "Build finished: $TAG"
if [ "$NO_CLEANUP" -eq 1 ] && [ "$TMP_CREATED" -eq 1 ]; then
  echo "Temporary secret kept at: $TMP_PATH"
fi
