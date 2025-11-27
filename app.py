# app.py
from flask import Flask, jsonify
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("nija_web")

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija Bot Running!", 200

    @app.route("/healthz")
    def healthz():
        # Attempt to import the test helper from nija_client (it may return False if not available)
        try:
            from nija_client import test_coinbase_connection
        except Exception as e:
            logger.warning("healthz: could not import test_coinbase_connection: %s", e)
            return jsonify({"ok": False, "reason": "nija_client missing or failed import"}), 500

        ok = test_coinbase_connection()
        return jsonify({"ok": bool(ok)}), (200 if ok else 503)

    return app

# Provide top-level `app` variable so gunicorn can load `web.wsgi:app` or `app:app`
app = create_app()
