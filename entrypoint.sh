#!/usr/bin/env bash
set -euo pipefail

# Source .env only if present (not recommended for production)
if [ -f /app/.env ]; then
  # shellcheck disable=SC1091
  source /app/.env || true
fi

echo "[INFO] PYTHONPATH=$PYTHONPATH"
python - <<'PY'
import sys, traceback

def try_import_check():
    # Try both possible package layouts
    names = [
        ("nija_client.check_funded", "from nija_client.check_funded import check_funded_accounts"),
        ("app.nija_client.check_funded", "from app.nija_client.check_funded import check_funded_accounts"),
    ]
    for mod_name, msg in names:
        try:
            mod = __import__(mod_name, fromlist=["check_funded_accounts"])
            func = getattr(mod, "check_funded_accounts", None)
            if callable(func):
                print(f"[INFO] Imported {mod_name}.check_funded_accounts")
                return func
            else:
                print(f"[WARN] {mod_name} imported but check_funded_accounts not found")
        except Exception as e:
            # hide noisy traceback but show a short message
            print(f"[DEBUG] import {mod_name} failed: {e}")
    return None

f = try_import_check()
if f is None:
    print("[ERROR] nija_client or check_funded.py missing (tried nija_client.check_funded and app.nija_client.check_funded).")
    sys.exit(1)

try:
    ok = bool(f())
except Exception as e:
    print("[ERROR] check_funded_accounts raised an exception:")
    traceback.print_exc()
    sys.exit(1)

if not ok:
    print("[ERROR] No funded accounts. Exiting.")
    sys.exit(2)

print("[INFO] Funded accounts check passed.")
PY

# start gunicorn using the canonical module path web.wsgi:application
exec gunicorn --config /app/gunicorn.conf.py web.wsgi:application
