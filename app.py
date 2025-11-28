# app.py
import logging
from flask import Flask, jsonify
from nija_client import test_coinbase_connection, coinbase_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija")

# -----------------------------------------------------------
# THE ONLY THING GUNICORN CARES ABOUT:
# This MUST exist at the top level. EXACT name: app
# -----------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "coinbase_available": coinbase_available()
    })

# -----------------------------------------------------------
# Startup check (non-blocking)
# -----------------------------------------------------------
try:
    LOG.info("Running startup Coinbase check...")
    test_coinbase_connection()
    LOG.info("Startup check finished.")
except Exception as e:
    LOG.exception("Startup check failed (non-fatal): %s", e)
