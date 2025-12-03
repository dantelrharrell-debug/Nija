#!/usr/bin/env bash
set -euo pipefail

# build_with_buildkit.sh
# Build the Nija Docker image using Docker BuildKit with a secret for GitHub token.
# This script creates a temporary secret file if you provide a token (or reads an existing secret file),
# runs a BuildKit-enabled docker build that mounts the secret at /run/secrets/github_token,
# and then securely removes the temporary secret file.
#
# Usage examples:
#   # Use an existing token file:
#   ./build_with_buildkit.sh --secret-file /path/to/tokenfile --target prod --tag nija:prod
#
#   # Provide token value directly (creates a secure temporary file, removed after build):
#   ./build_with_buildkit.sh --token "$GITHUB_TOKEN" --target prod --tag nija:prod
#
#   # Prompt for token interactively:
#   ./build_with_buildkit.sh --prompt --target prod --tag nija:prod
#
# Defaults:
#   target = prod
#   tag = nija:prod
#
# Notes:
#  - This script forces BuildKit for the build command (DOCKER_BUILDKIT=1).
#  - The Dockerfile must use /run/secrets/github_token in the builder stage to consume the secret.
#  - Avoid passing tokens as build-args; this script uses --secret which does not persist secrets in image layers.

print_help() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --secret-file PATH    Use an existing file containing the GitHub token (preferred).
  --token TOKEN         Provide token value on the command line (temporary file will be created).
  --prompt              Prompt interactively for token (no echo).
  --target TARGET       Docker build target stage (default: prod).
  --tag IMAGE_TAG       Docker image tag (default: nija:prod for prod, nija:dev for dev).
  --no-cleanup          Do not remove temporary token file (for debugging).
  -h, --help            Show this help and exit.

Examples:
  DOCKER_BUILDKIT=1 $0 --secret-file /tmp/github_token --target prod --tag nija:prod
  $0 --token "ghp_..." --target prod --tag nija:prod
  $0 --prompt --target dev --tag nija:dev

EOF
}

# Defaults
SECRET_FILE=""
TOKEN=""
PROMPT_TOKEN=0
TARGET="prod"
TAG=""
NO_CLEANUP=0

# Parse args
while [ $# -gt 0 ]; do
  case "$1" in
    --secret-file)
      SECRET_FILE="$2"; shift 2;;
    --token)
      TOKEN="$2"; shift 2;;
    --prompt)
      PROMPT_TOKEN=1; shift;;
    --target)
      TARGET="$2"; shift 2;;
    --tag)
      TAG="$2"; shift 2;;
    --no-cleanup)
      NO_CLEANUP=1; shift;;
    -h|--help)
      print_help; exit 0;;
    *)
      echo "Unknown arg: $1"
      print_help
      exit 2;;
  esac
done

# Infer default tag if not provided
if [ -z "$TAG" ]; then
  if [ "$TARGET" = "dev" ]; then
    TAG="nija:dev"
  else
    TAG="nija:prod"
  fi
fi

# Basic environment checks
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker CLI not found. Install Docker and try again."
  exit 1
fi

if [ ! -f Dockerfile ]; then
  echo "ERROR: Dockerfile not found in current directory: $(pwd)"
  exit 1
fi

# Prepare secret file: use provided file or create a temp file from token/prompt/env
TMP_SECRET_CREATED=0
TMP_SECRET_PATH=""

cleanup_secret() {
  if [ "$TMP_SECRET_CREATED" -eq 1 ] && [ "$NO_CLEANUP" -eq 0 ]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u -z "$TMP_SECRET_PATH" 2>/dev/null || rm -f "$TMP_SECRET_PATH"
    else
      rm -f "$TMP_SECRET_PATH"
    fi
    TMP_SECRET_CREATED=0
    TMP_SECRET_PATH=""
  fi
}
trap cleanup_secret EXIT

# Decide which secret path to use
if [ -n "${SECRET_FILE:-}" ]; then
  if [ ! -f "$SECRET_FILE" ]; then
    echo "ERROR: provided --secret-file does not exist: $SECRET_FILE"
    exit 1
  fi
  SECRET_PATH="$SECRET_FILE"
elif [ -n "${TOKEN:-}" ]; then
  TMP_SECRET_PATH="$(mktemp)"
  # use printf to avoid adding newline
  printf "%s" "$TOKEN" > "$TMP_SECRET_PATH"
  chmod 600 "$TMP_SECRET_PATH"
  TMP_SECRET_CREATED=1
  SECRET_PATH="$TMP_SECRET_PATH"
elif [ "$PROMPT_TOKEN" -eq 1 ]; then
  read -r -s -p "GitHub token: " TOKEN
  echo ""
  if [ -z "$TOKEN" ]; then
    echo "ERROR: no token entered"
    exit 1
  fi
  TMP_SECRET_PATH="$(mktemp)"
  printf "%s" "$TOKEN" > "$TMP_SECRET_PATH"
  chmod 600 "$TMP_SECRET_PATH"
  TMP_SECRET_CREATED=1
  SECRET_PATH="$TMP_SECRET_PATH"
elif [ -n "${GITHUB_TOKEN:-}" ]; then
  # Use environment token if present
  TMP_SECRET_PATH="$(mktemp)"
  printf "%s" "$GITHUB_TOKEN" > "$TMP_SECRET_PATH"
  chmod 600 "$TMP_SECRET_PATH"
  TMP_SECRET_CREATED=1
  SECRET_PATH="$TMP_SECRET_PATH"
else
  echo "ERROR: No token supplied. Provide --secret-file, --token, --prompt, or set GITHUB_TOKEN env var."
  print_help
  exit 1
fi

echo "Using secret file: $SECRET_PATH"
echo "Docker target: $TARGET"
echo "Image tag: $TAG"

# Build command using BuildKit secret (ensure BuildKit is enabled by prefixing DOCKER_BUILDKIT=1)
BUILD_CMD=(docker build --progress=plain --secret id=github_token,src="$SECRET_PATH" --target "$TARGET" -t "$TAG" .)

# Print the command in a redacted form (don't print token contents)
REDACTED_CMD=("${BUILD_CMD[@]}")
for i in "${!REDACTED_CMD[@]}"; do
  if [ "${REDACTED_CMD[$i]}" = "$SECRET_PATH" ]; then
    REDACTED_CMD[$i]="<secret_file>"
  fi
done

printf "Running BuildKit build (BuildKit forced):\nDOCKER_BUILDKIT=1"
for part in "${REDACTED_CMD[@]}"; do
  printf ' %q' "$part"
done
printf "\n\n"

# Execute the build
DOCKER_BUILDKIT=1 "${BUILD_CMD[@]}" || {
  echo "ERROR: docker build failed"
  exit 1
}

echo "Build completed: $TAG"

# cleanup happens via trap unless NO_CLEANUP is set
if [ "$NO_CLEANUP" -eq 1 ] && [ "$TMP_SECRET_CREATED" -eq 1 ]; then
  echo "Temporary secret file kept at: $TMP_SECRET_PATH"
fi

exit 0
