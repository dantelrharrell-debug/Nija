# web/wsgi.py
import sys

# Try both import locations so this file works regardless of layout
try:
    # preferred: top-level package nija_client
    from nija_client import app as application
    print("[INFO] Using nija_client.app as WSGI application")
except Exception:
    try:
        # fallback: nested inside app/ package
        from app.nija_client import app as application
        print("[INFO] Using app.nija_client.app as WSGI application")
    except Exception as e:
        # re-raise with clear message (Gunicorn will surface this)
        raise ImportError("Could not import nija_client.app or app.nija_client.app") from e
