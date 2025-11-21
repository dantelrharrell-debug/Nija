#!/usr/bin/env bash
set -euo pipefail

timestamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

echo "== START_ALL.SH: $(timestamp) =="

required=(COINBASE_API_KEY COINBASE_API_SECRET COINBASE_PEM_CONTENT)
missing=()
for v in "${required[@]}"; do
  if [ -z "${!v-}" ]; then
    echo "[$(timestamp)] ❌ $v not set"
    missing+=("$v")
  else
    echo "[$(timestamp)] ✅ $v present"
  fi
done

if [ "${#missing[@]}" -ne 0 ] && [ "${ALLOW_MISSING_ENV:-0}" != "1" ]; then
  echo "[$(timestamp)] ERROR: required env vars missing: ${missing[*]}"
  exit 1
fi

# ensure we are in /app
if cd /app 2>/dev/null; then
  echo "[$(timestamp)] INFO: changed directory to /app"
else
  echo "[$(timestamp)] WARN: /app not found; continuing in $(pwd)"
fi

PORT="${PORT:-5000}"
WORKERS="${WEB_CONCURRENCY:-1}"

start_gunicorn() {
  echo "[$(timestamp)] INFO: Starting gunicorn with $WORKERS worker(s) on :$PORT"
  exec gunicorn -w "$WORKERS" -k sync -b "0.0.0.0:${PORT}" main:app
}

start_python() {
  echo "[$(timestamp)] INFO: gunicorn not found; trying 'python -m gunicorn'"
  exec python -m gunicorn -w "$WORKERS" -k sync -b "0.0.0.0:${PORT}" main:app || {
    echo "[$(timestamp)] WARN: python -m gunicorn failed; falling back to 'python main.py'"
    exec python main.py
  }
}

if command -v gunicorn >/dev/null 2>&1; then
  start_gunicorn
else
  start_python
fi
