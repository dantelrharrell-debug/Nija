# web/wsgi.py
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

try:
    # prefer your factory if present
    from web import create_app
    logger.info("Using web.create_app() to build Flask app")
    app = create_app()
except Exception as e:
    logger.exception("web.create_app() failed: %s", e)
    # Minimal fallback app so Gunicorn starts and you can hit / and see error
    from flask import Flask, jsonify
    app = Flask(__name__)
    @app.route("/")
    def index():
        return jsonify({"ok": False, "error": "create_app import failed; check logs"})
