# web/wsgi.py
import os
import logging

# configure minimal logging so errors show in container logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

try:
    # If your factory is in web.__init__.py and called create_app():
    from web import create_app
    logger.info("Found web.create_app(), building app via factory")
    app = create_app()
except Exception as e:
    # If factory import fails, log full exception + fallback for simple app
    logger.exception("Failed to import create_app() from web — check import errors: %s", e)
    # Minimal fallback so Gunicorn can still start and you see errors on / route:
    from flask import Flask, jsonify
    app = Flask(__name__)
    @app.route("/")
    def index():
        return jsonify({"ok": False, "error": "app import failed; check logs"})
