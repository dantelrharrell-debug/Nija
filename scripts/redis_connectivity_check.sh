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

echo "[2/4] Selecting connectivity backend"
if command -v redis-cli >/dev/null 2>&1; then
  echo "Using redis-cli for connectivity check..."
  echo "[3/4] Running ping"
  redis-cli -u "${url}" ping
  echo "[4/4] Connectivity check completed"
  exit $?
fi

echo "redis-cli not found; using Python redis client fallback..."
echo "[3/4] Running ping"
python3 - <<'PY' "${url}"
import sys
try:
  import redis
except Exception as exc:
  print(f"ERROR: Python redis module not available: {exc}")
  raise SystemExit(2)

url = sys.argv[1]
try:
  client = redis.from_url(url, socket_connect_timeout=5, socket_timeout=5, decode_responses=True)
  print("PONG" if client.ping() else "ERROR")
except Exception as exc:
  print(f"ERROR: Redis connectivity check failed: {exc}")
  raise SystemExit(1)
PY
echo "[4/4] Connectivity check completed"
