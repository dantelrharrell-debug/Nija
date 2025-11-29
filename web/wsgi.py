import sys
import traceback

try:
    from web import app
except Exception as e:
    print("[ERROR] Failed to import `app` from web:", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)

# Gunicorn expects this variable
wsgi_app = app
