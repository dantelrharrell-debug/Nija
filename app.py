# app.py
import os
import logging
from flask import Flask, jsonify

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Nija bot web app running."

    @app.route("/healthz")
    def health():
        # try to import a smoke test from nija_client (non-blocking)
        coinbase_ok = False
        coinbase_msg = "not tested"
        try:
            # nija_client exposes a test function (see below)
            from nija_client import test_coinbase_connection
            coinbase_ok = test_coinbase_connection()
            coinbase_msg = "ok" if coinbase_ok else "failed"
        except Exception as e:
            coinbase_msg = f"skipped: {e}"
        return jsonify({"status": "ok", "coinbase_test_ok": coinbase_ok, "coinbase_msg": coinbase_msg})

    return app
