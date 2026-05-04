#!/usr/bin/env bash
set -euo pipefail

env_file="${1:-}"
if [ -n "${env_file}" ] && [ -f "${env_file}" ]; then
  # shellcheck disable=SC1090
  set -a
  . "${env_file}"
  set +a
  echo "Loaded env file: ${env_file}"
fi

# Source this script in your shell to keep exported vars:
#   source scripts/debug_startup_safe_mode.sh [optional-env-file]
export DRY_RUN_MODE=true
export LIVE_CAPITAL_VERIFIED=false

echo "Debug safety mode enabled"
echo "  DRY_RUN_MODE=${DRY_RUN_MODE}"
echo "  LIVE_CAPITAL_VERIFIED=${LIVE_CAPITAL_VERIFIED}"

redis_url="${NIJA_REDIS_URL:-${REDIS_URL:-${REDIS_PUBLIC_URL:-${REDIS_PRIVATE_URL:-}}}}"
if [ -z "${redis_url}" ]; then
  echo "No Redis URL found in NIJA_REDIS_URL/REDIS_URL/REDIS_PUBLIC_URL/REDIS_PRIVATE_URL"
  echo "If your Redis values are in an env file, run: source scripts/debug_startup_safe_mode.sh <env-file>"
else
  echo "Testing Redis URL from current environment..."
  if command -v redis-cli >/dev/null 2>&1; then
    if printf "%s" "${redis_url}" | grep -Eiq '^rediss://'; then
      redis_cmd=(redis-cli --tls -u "${redis_url}" ping)
    else
      redis_cmd=(redis-cli -u "${redis_url}" ping)
    fi

    set +e
    redis_out="$(${redis_cmd[@]} 2>&1)"
    redis_status=$?
    set -e

    echo "redis-cli output: ${redis_out}"
    if [ ${redis_status} -eq 0 ] && printf "%s" "${redis_out}" | grep -q "PONG"; then
      echo "Redis reachable"
    else
      echo "Redis unreachable"
      echo "Hint: if host is *.proxy.rlwy.net, URL should usually be rediss:// with valid password"
    fi
  else
    echo "redis-cli not installed in this shell; cannot run ping test"
  fi
fi

health_port="${PORT:-5000}"
if command -v curl >/dev/null 2>&1; then
  echo "Checking health endpoint on :${health_port}"
  curl -sS "http://127.0.0.1:${health_port}/healthz" || true
  echo
else
  echo "curl not installed; skipping health endpoint check"
fi

if [ -f "validate_broker_credentials.py" ] && command -v python3 >/dev/null 2>&1; then
  echo "Running broker configuration validator"
  python3 validate_broker_credentials.py || true
fi

echo "If health reports awaiting_configuration, run:"
echo "  python validate_broker_credentials.py"
