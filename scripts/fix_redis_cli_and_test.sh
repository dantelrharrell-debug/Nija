#!/usr/bin/env bash
set -euo pipefail

check_args=()
if [ "${1:-}" = "--env-file" ]; then
  check_args+=("--env-file" "${2:-}")
fi

echo "User: $(id -un) (uid=$(id -u))"

install_redis_cli() {
  if command -v redis-cli >/dev/null 2>&1; then
    echo "redis-cli already installed"
    return 0
  fi

  echo "redis-cli not found; installing redis-tools..."
  if command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
      apt-get update && apt-get install -y redis-tools
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update && sudo apt-get install -y redis-tools
    else
      echo "WARN: Need root or sudo to install redis-tools; continuing with Python fallback check"
      return 1
    fi
  else
    echo "WARN: apt-get not available; continuing with Python fallback check"
    return 1
  fi

  command -v redis-cli >/dev/null 2>&1 || {
    echo "WARN: redis-cli install did not succeed; continuing with Python fallback check"
    return 1
  }
}

install_redis_cli || true

echo "Running Redis connectivity check..."
if ! output=$(bash scripts/redis_connectivity_check.sh "${check_args[@]}" 2>&1); then
  status=$?
  echo "${output}"
  echo ""
  echo "FAILED: redis connectivity check exited with status ${status}"
  case "${status}" in
    2)
      echo "Hint: Python redis package is missing. Install dependencies with: pip install -r requirements.txt"
      ;;
    3)
      echo "Hint: TLS mismatch. Use rediss:// for Railway proxy host (*.proxy.rlwy.net) when NIJA_REDIS_FORCE_TLS=true"
      ;;
    4)
      echo "Hint: Redis vars are not exported in this shell. Export NIJA_REDIS_URL or run with --env-file <path>."
      ;;
    *)
      echo "Hint: Check Redis URL correctness, Railway Redis service status, and network reachability."
      ;;
  esac
  exit "${status}"
fi

echo "${output}"
echo "SUCCESS: Redis connectivity check passed"
