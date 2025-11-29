# app/wsgi.py
import os
import sys
import traceback
from flask import Flask

# attempt to import the exported `app` from the package
try:
    # `from app import app` expects app/__init__.py to set `app`
    from app import app  # app is the Flask instance created in app/__init__.py
except Exception as e:
    # Print full traceback to stdout so Railway/Render logs capture it
    print("[ERROR] Failed to import `app` from package 'app':", file=sys.stderr)
    traceback.print_exc()
    # Exit non-zero so the container logs show a clear failure (Gunicorn will mark worker as failed)
    # If you prefer the container to keep running and show message, comment out the sys.exit line.
    sys.exit(1)

# optional: a quick sanity route if you want a container-level endpoint for tests
@app.route("/")
def index():
    return "Nija Bot Running!", 200
