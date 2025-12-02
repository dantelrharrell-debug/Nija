#!/bin/bash
set -euo pipefail

echo "=== STARTUP CHECKS ==="

# 1) Print Python and pip locations
echo "[INFO] python: $(which python3 || echo 'not found')"
echo "[INFO] pip: $(which pip || echo 'not found')"
python3 --version || true

# 2) Verify Coinbase package import
python3 - <<'PY'
import sys
try:
    import coinbase
    print("[OK] 'coinbase' package import OK. __file__:", getattr(coinbase, '__file__', 'n/a'))
except Exception as e:
    print("[ERROR] cannot import 'coinbase' package:", repr(e))
    sys.exit(10)
PY

# 3) Ensure required environment variables exist
missing=()
for v in COINBASE_API_KEY COINBASE_API_SECRET COINBASE_API_PASSPHRASE; do
  if [ -z "${!v:-}" ]; then
    missing+=("$v")
  fi
done

if [ ${#missing[@]} -gt 0 ]; then
  echo "[ERROR] Missing environment variables: ${missing[*]}"
  echo "Set them with your platform's env UI or with --env-file / -e for local docker."
  exit 11
fi

# 4) Run a small health check that validates your bot module and start_trading_loop symbol
python3 health_check.py || { echo "[ERROR] health_check.py failed"; exit 12; }

echo "=== STARTING GUNICORN ==="
exec gunicorn -c gunicorn.conf.py web.wsgi:app
