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
    """
    Import nija_client and run lightweight checks here.
    This runs after import-time so failures won't prevent Gunicorn from importing this module.
    """
    LOG.info("Running lazy startup checks (before_first_request).")
    try:
        # Import inside function — prevents import-time side effects from crashing Gunicorn
        try:
            from nija_client import test_coinbase_connection, coinbase_available
        except Exception as exc:
            # handle normal exceptions (ImportError, ModuleNotFoundError, etc.)
            LOG.exception("Could not import nija_client: %s", exc)
            _set_coinbase_flag(False)
            return
        except BaseException as bexc:
            # Catch SystemExit/KeyboardInterrupt or other BaseExceptions raised at import time
            LOG.error("nija_client import raised BaseException (fatal during import): %s", bexc)
            # Don't re-raise here; set flag false and continue to keep the worker alive
            _set_coinbase_flag(False)
            return

        # If we got here, import succeeded — check availability, but guard the check as well
        try:
            LOG.info("Running test_coinbase_connection() now.")
            test_coinbase_connection()  # may raise; catch below
            avail = False
            try:
                # coinbase_available may be a callable or boolean — handle both
                avail = coinbase_available() if callable(coinbase_available) else bool(coinbase_available)
            except Exception:
                LOG.exception("coinbase_available() call failed; defaulting to False.")
                avail = False

            _set_coinbase_flag(avail)
            LOG.info("Coinbase available flag set to: %s", avail)
        except BaseException as be:
            # catch everything (SystemExit etc.) so that the worker does not die
            LOG.exception("test_coinbase_connection raised during startup: %s", be)
            _set_coinbase_flag(False)

    except Exception:
        # Failsafe so no import-time issues occur
        LOG.exception("Unexpected error during lazy startup checks.")
        _set_coinbase_flag(False)

# ----------------------------
# Local dev run
# ----------------------------
if __name__ == "__main__":
    LOG.info("Starting local Flask server (dev only)")
    # Run the startup check manually in dev launch
    try:
        run_startup_checks()
    except Exception:
        LOG.exception("Startup checks failed during local run.")
    app.run(host="0.0.0.0", port=8080, debug=False)
