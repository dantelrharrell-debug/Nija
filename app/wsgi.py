import os
import sys
import traceback

# attempt to import the exported `app` from the package
try:
    from app import app  # app is the Flask instance created in app/__init__.py
except Exception as e:
    print("[ERROR] Failed to import `app` from package 'app':", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)

# This is what Gunicorn uses
wsgi_app = app

# optional: a quick sanity route if you want a container-level endpoint for tests
from app import app

@app.route("/")
def index():
    return "Nija Bot Running!", 200
