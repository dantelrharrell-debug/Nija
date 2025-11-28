# app.py (Robust, copy-paste ready)
import logging
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija")

# IMPORTANT: this top-level variable must be named `app`
app = Flask(__name__)

# Try to import nija_client but don't crash if it fails
coinbase_available_flag = False
try:
    # import lazily to avoid import-time crashes
    from nija_client import test_coinbase_connection, coinbase_available  # noqa: E402
    coinbase_available_flag = coinbase_available()
    LOG.info("Imported nija_client successfully.")
except Exception as e:
    LOG.exception("Could not import nija_client at startup (continuing). %s", e)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "coinbase_available": coinbase_available_flag
    })

# Local dev runner (only used if you run python app.py)
if __name__ == "__main__":
    try:
        LOG.info("Running startup check...")
        if 'test_coinbase_connection' in globals():
            test_coinbase_connection()
        LOG.info("Startup check done.")
    except Exception:
        LOG.exception("Startup check raised an exception.")
    app.run(host="0.0.0.0", port=8080)
