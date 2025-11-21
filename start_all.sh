#!/usr/bin/env bash
set -euo pipefail
echo "== START_ALL.SH: $(date -u) =="
for v in COINBASE_API_KEY COINBASE_API_SECRET COINBASE_PEM_CONTENT; do
  [ -z "${!v:-}" ] && echo "❌ $v not set" || echo "✅ $v present"
done
cd /app || true
if command -v gunicorn >/dev/null 2>&1; then
  exec gunicorn -w 1 -k sync -b 0.0.0.0:${PORT:-5000} main:app
else
  echo "gunicorn not available; attempting python main.py"
  exec python main.py
fi
