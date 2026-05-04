#!/usr/bin/env bash
set -euo pipefail

env_file="${NIJA_ENV_FILE:-}"
if [ "${1:-}" = "--env-file" ]; then
  env_file="${2:-}"
fi

load_env_file() {
  local file_path="$1"
  if [ -z "${file_path}" ]; then
    return 0
  fi
  if [ ! -f "${file_path}" ]; then
    echo "ERROR: env file not found: ${file_path}"
    return 1
  fi

  # shellcheck disable=SC1090
  set -a
  . "${file_path}"
  set +a
  echo "Loaded env file: ${file_path}"
}

if [ -n "${env_file}" ]; then
  load_env_file "${env_file}"
fi

force_tls="${NIJA_REDIS_FORCE_TLS:-true}"
strict_checks="${NIJA_REDIS_STRICT_CHECKS:-true}"

is_truthy() {
  printf "%s" "${1:-}" | grep -Eiq '^(1|true|yes|on|enabled)$'
}

railway_best_effort_status() {
  if ! command -v railway >/dev/null 2>&1; then
    echo "INFO: Railway CLI not installed; skipping direct service status check"
    return 0
  fi

  local status_output status_lower
  if ! status_output="$(railway status 2>/dev/null || true)"; then
    echo "WARN: Could not read Railway status"
    return 0
  fi

  if [ -z "${status_output}" ]; then
    echo "WARN: Railway status output is empty (CLI may not be linked/login may be required)"
    if is_truthy "${strict_checks}"; then
      return 1
    fi
    return 0
  fi

  status_lower="$(printf "%s" "${status_output}" | tr '[:upper:]' '[:lower:]')"
  if printf "%s" "${status_lower}" | grep -Eq 'redis'; then
    echo "Railway status includes a Redis service entry"
  else
    echo "WARN: Railway status did not mention a Redis service"
    if is_truthy "${strict_checks}"; then
      return 1
    fi
  fi

  if printf "%s" "${status_lower}" | grep -Eq 'deployed|success|running|active|healthy'; then
    echo "Railway reports at least one active deployment state"
  else
    echo "WARN: Railway status does not clearly indicate an active deployment"
    if is_truthy "${strict_checks}"; then
      return 1
    fi
  fi
}

verify_network_linkage() {
  local host="$1"
  if printf "%s" "${host}" | grep -Eiq '\.railway\.internal$'; then
    echo "Using Railway internal Redis hostname: ${host}"
    if [ -n "${RAILWAY_PROJECT_ID:-}" ] && [ -n "${RAILWAY_ENVIRONMENT_ID:-}" ]; then
      echo "Railway runtime context present (RAILWAY_PROJECT_ID + RAILWAY_ENVIRONMENT_ID)"
      echo "Assuming same-project private network linkage for internal hostname"
    else
      echo "WARN: Internal Railway host requires NIJA and Redis services in same Railway project/environment"
      echo "      Missing runtime linkage vars (RAILWAY_PROJECT_ID and/or RAILWAY_ENVIRONMENT_ID) in this shell"
      if is_truthy "${strict_checks}"; then
        return 1
      fi
    fi
    return 0
  fi

  if printf "%s" "${host}" | grep -Eiq '\.proxy\.rlwy\.net$'; then
    echo "Using Railway public TCP proxy hostname: ${host}"
    echo "Public proxy does not require private same-project networking"
    return 0
  fi

  echo "INFO: Host does not match Railway internal/proxy patterns; skipping Railway linkage checks"
}

run_port_reachability_test() {
  local host="$1"
  local port="$2"

  echo "Testing TCP reachability to ${host}:${port}"
  if command -v nc >/dev/null 2>&1; then
    if nc -z -w 5 "${host}" "${port}"; then
      echo "nc reachability test passed"
      return 0
    fi
    echo "ERROR: nc reachability test failed for ${host}:${port}"
    return 1
  fi

  echo "nc not found; using Python socket fallback"
  python3 - <<'PY' "${host}" "${port}"
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
try:
    sock.connect((host, port))
    print("socket reachability test passed")
except Exception as exc:
    print(f"ERROR: socket reachability test failed: {exc}")
    raise SystemExit(1)
finally:
    sock.close()
PY
}

resolve_redis_url() {
  if [ -n "${NIJA_REDIS_URL:-}" ]; then
    printf "%s" "${NIJA_REDIS_URL}"
    return 0
  fi
  if [ -n "${REDIS_URL:-}" ]; then
    printf "%s" "${REDIS_URL}"
    return 0
  fi
  if [ -n "${REDIS_TLS_URL:-}" ]; then
    printf "%s" "${REDIS_TLS_URL}"
    return 0
  fi
  if [ -n "${REDIS_PRIVATE_URL:-}" ]; then
    printf "%s" "${REDIS_PRIVATE_URL}"
    return 0
  fi
  if [ -n "${REDIS_PUBLIC_URL:-}" ]; then
    printf "%s" "${REDIS_PUBLIC_URL}"
    return 0
  fi

  local host port password db scheme
  host="${RAILWAY_TCP_PROXY_DOMAIN:-${REDIS_HOST:-${REDISHOST:-}}}"
  port="${RAILWAY_TCP_PROXY_PORT:-${REDIS_PORT:-${REDISPORT:-}}}"
  password="${REDIS_PASSWORD:-${REDISPASSWORD:-${REDIS_TOKEN:-}}}"
  db="${REDIS_DB:-${REDIS_DATABASE:-0}}"

  if [ -z "${host}" ] || [ -z "${port}" ]; then
    return 1
  fi
  if ! printf "%s" "${port}" | grep -Eq '^[0-9]+$'; then
    return 1
  fi

  scheme="redis"
  if printf "%s" "${host}" | grep -Eiq '\.proxy\.rlwy\.net$' \
    && printf "%s" "${force_tls}" | grep -Eiq '^(1|true|yes|on|enabled)$'; then
    scheme="rediss"
  fi

  if [ -n "${password}" ]; then
    printf "%s" "${scheme}://default:${password}@${host}:${port}/${db}"
  else
    printf "%s" "${scheme}://${host}:${port}/${db}"
  fi
  return 0
}

url="$(resolve_redis_url || true)"

if [ -z "${url}" ]; then
  echo "ERROR: Redis URL is empty"
  echo "Checked: NIJA_REDIS_URL, REDIS_URL, REDIS_TLS_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL"
  echo "Also checked component vars: RAILWAY_TCP_PROXY_DOMAIN/PORT, REDIS_HOST/PORT, REDIS_PASSWORD"
  echo "Tip: pass an env file with --env-file <path> if variables are not exported in this shell"
  exit 4
fi

echo "[1/4] Validating Redis URL"

safe_url="$(python3 - <<'PY' "${url}"
import sys
from urllib.parse import urlparse

raw = sys.argv[1]
parsed = urlparse(raw)
host = parsed.hostname or "<unknown-host>"
try:
  port = parsed.port or "<unknown-port>"
except ValueError:
  port = "<invalid-port>"
print(f"{parsed.scheme}://***@{host}:{port}")
PY
)"

echo "Redis URL: ${safe_url}"
echo "NIJA_REDIS_FORCE_TLS=${force_tls}"

host_and_port="$(python3 - <<'PY' "${url}"
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
host = parsed.hostname or ""
port = parsed.port or ""
scheme = parsed.scheme or ""
print(f"{host}|{port}|{scheme}")
PY
)"
redis_host="${host_and_port%%|*}"
remaining="${host_and_port#*|}"
redis_port="${remaining%%|*}"
redis_scheme="${remaining##*|}"

if [ -z "${redis_host}" ] || [ -z "${redis_port}" ]; then
  echo "ERROR: Could not parse Redis host/port from URL"
  exit 4
fi

if python3 - <<'PY' "${url}" "${force_tls}"
import sys
from urllib.parse import urlparse

raw = sys.argv[1]
force_tls = sys.argv[2].strip().lower() in {"1", "true", "yes", "on", "enabled"}
parsed = urlparse(raw)
host = (parsed.hostname or "").lower()
if force_tls and parsed.scheme == "redis" and host.endswith(".proxy.rlwy.net"):
    print("ERROR: NIJA_REDIS_URL uses redis:// on Railway proxy while NIJA_REDIS_FORCE_TLS=true")
    print("Set NIJA_REDIS_URL to rediss://...")
    raise SystemExit(3)
raise SystemExit(0)
PY
then
  :
else
  exit 3
fi

echo "[2/5] Confirming Redis service status in Railway (best effort)"
if ! railway_best_effort_status; then
  echo "ERROR: Railway service status check failed"
  echo "Hint: ensure railway CLI is linked/logged in and Redis is deployed/running"
  exit 5
fi

echo "[3/5] Verifying project/network linkage"
if ! verify_network_linkage "${redis_host}"; then
  echo "ERROR: Railway project/network linkage check failed"
  echo "Hint: for *.railway.internal hosts, NIJA and Redis must be in same Railway project/environment"
  exit 6
fi

echo "[4/5] Running nc port reachability test"
run_port_reachability_test "${redis_host}" "${redis_port}"

echo "[5/5] Running Redis ping with explicit TLS support"
if command -v redis-cli >/dev/null 2>&1; then
  echo "Using redis-cli for connectivity check..."
  if [ "${redis_scheme}" = "rediss" ]; then
    redis-cli --tls -u "${url}" ping
  else
    redis-cli -u "${url}" ping
  fi
  echo "Connectivity check completed"
  exit $?
fi

echo "redis-cli not found; using Python redis client fallback..."
python3 - <<'PY' "${url}"
import sys
try:
  import redis
except Exception as exc:
  print("Redis failed:", exc)
  raise SystemExit(2)

url = sys.argv[1]
try:
  r = redis.from_url(url, socket_timeout=3)
  r.ping()
  print("Redis OK")
except Exception as e:
  print("Redis failed:", e)
  raise SystemExit(1)
PY
echo "Connectivity check completed"
