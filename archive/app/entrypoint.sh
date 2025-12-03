#!/usr/bin/env bash
set -euo pipefail

# optionally load .env if present in image (NOT recommended for production)
if [ -f /app/.env ]; then
  # shellcheck disable=SC1090
  source /app/.env || true
fi

# Run funded-account check (importable Python script must exist)
python - <<'PY'
import sys
try:
    # app package is under app/nija_client if you followed structure
    from app.nija_client.check_funded import check_funded_accounts
except Exception as e:
    print("[ERROR] nija_client/check_funded import failed:", e)
    sys.exit(1)

ok = False
try:
    ok = bool(check_funded_accounts())
except Exception as e:
    print("[ERROR] check_funded_accounts raised exception:", e)
    sys.exit(1)

if not ok:
    print("[ERROR] No funded accounts found. Exiting.")
    sys.exit(2)

print("[INFO] Funded accounts found. Starting Gunicorn.")
PY

# Exec gunicorn using web.wsgi:app (adjust module path if different)
exec gunicorn --config /app/gunicorn.conf.py web.wsgi:app
