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
    set +e
    python3 - <<'PY' "${redis_url}"
import subprocess
import sys
from urllib.parse import urlparse

REDIS_CLI_TIMEOUT_S = 5
raw = sys.argv[1]
parsed = urlparse(raw)
host = parsed.hostname or ""
port = parsed.port or ""
scheme = (parsed.scheme or "").lower()
user = parsed.username or ""
password = parsed.password or ""
db_raw = (parsed.path or "").lstrip("/")
db = db_raw if db_raw.isdigit() else "0"

is_proxy = host.lower().endswith(".proxy.rlwy.net")
use_tls = scheme == "rediss" or is_proxy

cmd = ["redis-cli", "-h", host, "-p", str(port), "-n", str(db)]
if user:
    cmd.extend(["--user", user])
if password:
    cmd.extend(["-a", password])
if use_tls:
    cmd.extend(["--tls", "--insecure"])
cmd.append("ping")

try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=REDIS_CLI_TIMEOUT_S)
except subprocess.TimeoutExpired:
    print("STDOUT: (empty)")
    print(f"STDERR: redis-cli timed out after {REDIS_CLI_TIMEOUT_S}s")
    print("RETURN CODE: 124")
    print("❌ REDIS PREFLIGHT FAILED")
    raise SystemExit(1)

stdout = (result.stdout or "").strip()
stderr = (result.stderr or "").strip()
print(f"STDOUT: {stdout if stdout else '(empty)'}")
print(f"STDERR: {stderr if stderr else '(empty)'}")
print(f"RETURN CODE: {result.returncode}")

if "PONG" in result.stdout:
    print("✅ REDIS PREFLIGHT SUCCESS")
    raise SystemExit(0)

print("❌ REDIS PREFLIGHT FAILED")
raise SystemExit(result.returncode or 1)
PY
    redis_status=$?
    set -e

    if [ ${redis_status} -eq 0 ]; then
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
