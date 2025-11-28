# app.py
import logging
from flask import Flask, jsonify

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija")

# ----------------------------
# Flask app (must be top-level)
# ----------------------------
app = Flask(__name__)  # <-- top-level variable, Gunicorn requires this

# ----------------------------
# Coinbase client import (safe)
# ----------------------------
coinbase_available_flag = False
try:
    from nija_client import test_coinbase_connection, coinbase_available
    coinbase_available_flag = coinbase_available()
    LOG.info("nija_client imported successfully.")
except Exception as e:
    LOG.exception("Could not import nija_client at startup. Continuing without it: %s", e)

# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "coinbase_available": coinbase_available_flag
    })

# ----------------------------
# Local startup check
# ----------------------------
if __name__ == "__main__":
    LOG.info("Starting local Flask server (dev only)")
    try:
        if 'test_coinbase_connection' in globals():
            LOG.info("Running Coinbase connection test...")
            test_coinbase_connection()
            LOG.info("Coinbase test done.")
    except Exception:
        LOG.exception("Coinbase test failed.")
    
    app.run(host="0.0.0.0", port=8080, debug=False)
