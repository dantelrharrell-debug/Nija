# web/wsgi.py
# This file must expose a WSGI application named "application".

# If your Flask app is a factory (create_app), import and call it.
try:
    # common pattern: app/web_app.py contains create_app()
    from app.web_app import create_app
    application = create_app()
except Exception:
    # fallback: maybe you have a flat Flask instance at app.web_app.app
    try:
        from app.web_app import app as application
    except Exception:
        # Last resort: small default app so container doesn't crash
        from flask import Flask
        application = Flask(__name__)

        @application.route("/_health")
        def _health():
            return "ok", 200
