# -----------------------
# Verify WSGI app
# -----------------------
WSGI_MODULE="web.wsgi:app"
echo "[INFO] Checking WSGI module $WSGI_MODULE..."
python - <<'PY'
import importlib
import sys
import traceback

try:
    mod_name, app_name = '$WSGI_MODULE'.split(':')
    mod = importlib.import_module(mod_name)
    getattr(mod, app_name)
    print(f"{WSGI_MODULE} import ok")
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY
