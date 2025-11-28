# app.py
import logging
import traceback
from flask import Flask, jsonify

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija")

# ----------------------------
# Flask app (top-level, as required by gunicorn)
# ----------------------------
app = Flask(__name__)

# runtime flag — default False until we check
_coinbase_available_flag = False

def get_coinbase_flag():
    return _coinbase_available_flag

def _set_coinbase_flag(val: bool):
    global _coinbase_available_flag
    _coinbase_available_flag = bool(val)

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
        "coinbase_available": get_coinbase_flag()
    })

# ----------------------------
# Lazy startup checks (safe)
# ----------------------------
@app.before_first_request
def run_startup_checks():
    LOG.info("Running lazy startup checks (before_first_request).")
    try:
        try:
            # import inside function — prevents import-time side effects
            from nija_client import test_coinbase_connection, coinbase_available
        except Exception as exc:
            LOG.exception("Could not import nija_client: %s", exc)
            _set_coinbase_flag(False)
            return
        except BaseException as bexc:
            LOG.error("nija_client import raised BaseException; skipping. %s", bexc)
            _set_coinbase_flag(False)
            return

        # If import succeeded, run the connection test guarded
        try:
            LOG.info("Running test_coinbase_connection() now.")
            test_coinbase_connection()
            avail = False
            try:
                avail = coinbase_available() if callable(coinbase_available) else bool(coinbase_available)
            except Exception:
                LOG.exception("coinbase_available() call failed; defaulting to False.")
                avail = False

            _set_coinbase_flag(avail)
            LOG.info("Coinbase available flag set to: %s", avail)
        except BaseException as be:
            LOG.exception("test_coinbase_connection raised during startup: %s", be)
            _set_coinbase_flag(False)

    except Exception:
        LOG.exception("Unexpected error during lazy startup checks.")
        _set_coinbase_flag(False)

# ----------------------------
# Local dev run
# ----------------------------
if __name__ == "__main__":
    LOG.info("Starting local Flask server (dev only)")
    try:
        run_startup_checks()
    except Exception:
        LOG.exception("Startup checks failed during local run.")
    app.run(host="0.0.0.0", port=8080, debug=False)
