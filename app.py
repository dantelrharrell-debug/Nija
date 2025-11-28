# app.py (Robust version)
import logging
import os
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija")

# IMPORTANT: gunicorn expects a top-level variable named `app`.
app = Flask(__name__)

# Try to import nija_client but don't crash if it fails
coinbase_available_flag = False
try:
    # import lazily to avoid import-time crashes
    from nija_client import test_coinbase_connection, coinbase_available, start_trading_loop  # noqa: E402
    coinbase_available_flag = coinbase_available()
    LOG.info("Imported nija_client successfully. coinbase_available=%s", coinbase_available_flag)
except Exception as e:
    LOG.exception("Could not import nija_client at startup (continuing). %s", e)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "coinbase_available": coinbase_available_flag,
        "live_trading": os.getenv("LIVE_TRADING", "0")
    })

# Do a non-blocking startup check when running locally
if __name__ == "__main__":
    try:
        LOG.info("Running local startup check...")
        if 'test_coinbase_connection' in globals():
            test_coinbase_connection()
        LOG.info("Startup check done.")
    except Exception:
        LOG.exception("Startup check raised an exception.")
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
