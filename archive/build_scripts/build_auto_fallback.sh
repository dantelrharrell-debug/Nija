#!/usr/bin/env bash
set -euo pipefail

# build_auto_fallback.sh
# 1) Attempts secure BuildKit build with secret (preferred).
# 2) If the remote builder rejects secret mounts (missing type=cache error), prompts you to:
#    A) Commit cd/vendor/coinbase_advanced_py into the repo and rebuild (recommended for remote builders),
#    B) Fallback to insecure --build-arg clone (token may leak; revoke after use),
#    C) Cancel.
#
# Usage:
#   ./build_auto_fallback.sh --secret-file /tmp/github_token --target prod --tag nija:prod
#   ./build_auto_fallback.sh --token "$GITHUB_TOKEN" --target prod --tag nija:prod
#   ./build_auto_fallback.sh --no-secret --target prod --tag nija:prod   # if vendor is committed locally
#
# Notes:
#  - This script will NOT print your token.
#  - If you choose to commit vendor, you will be prompted to confirm before git push runs.
#  - If you choose the insecure fallback, revoke the PAT after use.

print_help() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --secret-file PATH   Use existing token file (file content only).
  --token TOKEN        Provide token string (temporary file created).
  --no-secret          Do not attempt a secret build (use local vendor or other options).
  --target TARGET      Docker target (default: prod).
  --tag IMAGE_TAG      Docker image tag (default: nija:prod).
  -h, --help           Show this help.
EOF
}

# defaults
SECRET_FILE=""
TOKEN=""
NO_SECRET=0
TARGET="prod"
TAG="nija:prod"

# parse args
while [ $# -gt 0 ]; do
  case "$1" in
    --secret-file) SECRET_FILE="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --no-secret) NO_SECRET=1; shift;;
    --target) TARGET="$2"; shift 2;;
    --tag) TAG="$2"; shift 2;;
    -h|--help) print_help; exit 0;;
    *) echo "Unknown arg: $1"; print_help; exit 2;;
  esac
done

if [ -z "$TAG" ]; then
  TAG="nija:${TARGET}"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker CLI not found."
  exit 1
fi

if [ ! -f Dockerfile ]; then
  echo "ERROR: Dockerfile not found in $(pwd)"
  exit 1
fi

# prepare secret file if requested
TMP_CREATED=0
TMP_PATH=""

cleanup() {
  if [ "$TMP_CREATED" -eq 1 ] && [ -n "$TMP_PATH" ]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u -z "$TMP_PATH" 2>/dev/null || rm -f "$TMP_PATH"
    else
      rm -f "$TMP_PATH"
    fi
  fi
}
trap cleanup EXIT

if [ "$NO_SECRET" -eq 0 ]; then
  if [ -n "$SECRET_FILE" ]; then
    if [ ! -f "$SECRET_FILE" ]; then
      echo "ERROR: secret file not found: $SECRET_FILE"
      exit 1
    fi
    SECRET_PATH="$SECRET_FILE"
  elif [ -n "$TOKEN" ]; then
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
    # No token provided, will attempt normal build using local vendor if present
    SECRET_PATH=""
  fi
else
  SECRET_PATH=""
fi

echo "Target: $TARGET"
echo "Tag: $TAG"
if [ -n "$SECRET_PATH" ]; then
  echo "Will attempt BuildKit secret build (secret file provided)."
else
  echo "No secret provided or --no-secret specified. Will attempt normal build using local vendor (if present)."
fi

# function to run build with optional secret
run_build_with_secret() {
  local secret="$1"
  local build_cmd
  if [ -n "$secret" ]; then
    build_cmd=(docker build --progress=plain --secret id=github_token,src="$secret" --target "$TARGET" -t "$TAG" .)
    echo "Running BuildKit build (secret). (DOCKER_BUILDKIT=1)"
    DOCKER_BUILDKIT=1 "${build_cmd[@]}" 2>&1 | tee build_attempt.log
    return "${PIPESTATUS[0]}"
  else
    build_cmd=(docker build --progress=plain --target "$TARGET" -t "$TAG" .)
    echo "Running normal docker build (no secret)..."
    "${build_cmd[@]}" 2>&1 | tee build_attempt.log
    return "${PIPESTATUS[0]}"
  fi
}

# attempt secure BuildKit build first if we have a secret
if [ -n "${SECRET_PATH:-}" ]; then
  set +e
  run_build_with_secret "$SECRET_PATH"
  rc=$?
  set -e
  if [ $rc -eq 0 ]; then
    echo "Build succeeded (BuildKit secret path)."
    exit 0
  fi

  # examine log to see if failure is the secret/mount error
  if grep -Fq "missing a type=cache argument" build_attempt.log || grep -Fqi "missing a type=cache" build_attempt.log; then
    echo ""
    echo "Detected remote builder does not support BuildKit secret mounts (error: missing a type=cache argument)."
    echo "You have three options:"
    echo "  1) Commit cd/vendor/coinbase_advanced_py into the repo so COPY works on the remote builder (recommended)."
    echo "  2) Retry using an insecure fallback (pass a token via --build-arg)."
    echo "  3) Cancel and choose another approach."
    echo ""
    PS3="Choose fallback action (1 commit vendor, 2 insecure build-arg, 3 cancel): "
    select opt in "Commit vendor and rebuild" "Insecure build-arg fallback" "Cancel"; do
      case $REPLY in
        1)
          echo "You chose: commit vendor and rebuild."
          # ensure vendor path exists
          if [ ! -d "cd/vendor/coinbase_advanced_py" ]; then
            echo "ERROR: vendor folder cd/vendor/coinbase_advanced_py not present locally. Cannot commit."
            exit 1
          fi
          echo "Staging cd/vendor/coinbase_advanced_py..."
          git add cd/vendor/coinbase_advanced_py
          if ! git diff --staged --quiet; then
            read -r -p "About to commit and push vendor folder to remote. Proceed? [y/N]: " confirm
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
              git commit -m "Add vendor/coinbase_advanced_py for Docker build"
              echo "Pushing to origin $(git rev-parse --abbrev-ref HEAD)..."
              git push
            else
              echo "Commit canceled by user."
              exit 1
            fi
          else
            echo "No staged changes for vendor; continuing."
          fi
          # rebuild without secret (local vendor will be used)
          echo "Re-running docker build (no secret)..."
          docker build --progress=plain --target "$TARGET" -t "$TAG" .
          exit $?
          ;;
        2)
          echo "You chose: insecure build-arg fallback."
          # request token if not present
          if [ -z "${TOKEN:-}" ] && [ -z "${SECRET_PATH:-}" ]; then
            read -r -s -p "Enter GitHub token (will be passed as build-arg; revoke after use): " entered
            echo ""
            if [ -z "$entered" ]; then
              echo "No token entered. Cancelling."
              exit 1
            fi
            TOKEN_FALLBACK="$entered"
          else
            # prefer original token if provided
            if [ -n "${TOKEN:-}" ]; then
              TOKEN_FALLBACK="$TOKEN"
            elif [ -n "${SECRET_PATH:-}" ]; then
              TOKEN_FALLBACK="$(cat "$SECRET_PATH")"
            else
              echo "No token available for fallback."
              exit 1
            fi
          fi
          echo "Running insecure build with --build-arg (token will be passed to docker build)."
          echo "WARNING: This may expose your token in build logs/image history. Revoke the PAT after use."
          # run build (do not echo token)
          docker build --progress=plain --build-arg GITHUB_TOKEN="${TOKEN_FALLBACK}" --target "$TARGET" -t "$TAG" .
          rc2=$?
          echo "Insecure build exit code: $rc2"
          echo "IMPORTANT: If this used a real PAT, revoke it immediately in GitHub settings:"
          echo "  https://github.com/settings/tokens"
          exit $rc2
          ;;
        3)
          echo "Cancelled by user."
          exit 1
          ;;
        *)
          echo "Invalid selection."
          ;;
      esac
    done
  else
    echo "Build failed for a reason other than the secret-mount compatibility. See build_attempt.log for details."
    echo "Tail of build log:"
    tail -n 200 build_attempt.log
    exit $rc
  fi
else
  # No secret attempt: just run normal build (using local vendor if present)
  docker build --progress=plain --target "$TARGET" -t "$TAG" .
  exit $?
fi
