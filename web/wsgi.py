# web/wsgi.py
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

try:
    from web import create_app
    logger.info("Calling web.create_app()")
    app = create_app()
except Exception:
    logger.exception("create_app() failed — falling back to minimal app")
    from flask import Flask, jsonify
    app = Flask(__name__)
    @app.route("/")
    def index():
        return jsonify({"ok": False, "error": "create_app() failed; check logs"})
    @app.route("/__diagnose")
    def diag():
        return jsonify({"ok": False, "diagnostic": "create_app() exception logged"})
