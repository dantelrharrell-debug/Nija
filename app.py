# app.py
import logging
from flask import Flask, jsonify
# import only the function for the startup check; nija_client should NOT create a Flask app
from nija_client import test_coinbase_connection, coinbase_available

LOG = logging.getLogger("nija")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# top-level Flask app object (Gunicorn looks for this)
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/healthz")
def healthz():
    # Basic health endpoint for container platforms
    return jsonify({"status": "ok", "coinbase_client": bool(coinbase_available())})

# run a startup check when the app object is imported (safe and non-blocking)
# this will log the result but will NOT call app.run() or exit the process
try:
    LOG.info("Running startup Coinbase check...")
    test_coinbase_connection()
    LOG.info("Startup check completed.")
except Exception as e:
    LOG.exception("Startup check failed (non-fatal): %s", e)
