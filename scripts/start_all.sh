#!/usr/bin/env bash
set -euo pipefail

echo "=== NIJA STARTUP: $(date -u) ==="

echo "[ENV CHECK]"
for v in COINBASE_API_KEY COINBASE_API_SECRET COINBASE_PEM_CONTENT; do
  if [ -z "${!v:-}" ]; then
    echo "❌ $v is NOT SET"
  else
    echo "✅ $v present"
  fi
done

# Ensure we're in /app
cd /app || cd .

echo "[START] Launching NIJA bot via Gunicorn..."
if command -v gunicorn >/dev/null 2>&1; then
  exec gunicorn -w 1 -k sync -b 0.0.0.0:${PORT:-5000} main:app
else
  echo "⚠️ Gunicorn not installed, using fallback: python main.py"
  exec python main.py
fi
