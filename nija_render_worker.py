# nija_render_worker.py
import os
import logging
import importlib.util

# --- Startup runtime debug (must run before importing nija_client) ---
logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # ensure at least one handler so messages appear in Render logs
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logger.info("[NIJA-DEBUG] BEGIN runtime import/env check")

try:
    spec = importlib.util.find_spec("coinbase_advanced_py.client")
    logger.info(f"[NIJA-DEBUG] coinbase_advanced_py.client importable: {spec is not None}")
except Exception as e:
    logger.info(f"[NIJA-DEBUG] importlib check failed: {e}")

def _masked(v):
    if v is None:
        return None
    v = str(v)
    if len(v) <= 8:
        return "****"
    return v[:4] + "..." + v[-4:]

logger.info(f"[NIJA-DEBUG] COINBASE_API_KEY present: {os.getenv('COINBASE_API_KEY') is not None} value={_masked(os.getenv('COINBASE_API_KEY'))}")
logger.info(f"[NIJA-DEBUG] COINBASE_API_SECRET present: {os.getenv('COINBASE_API_SECRET') is not None} value={_masked(os.getenv('COINBASE_API_SECRET'))}")
logger.info(f"[NIJA-DEBUG] COINBASE_API_PASSPHRASE present: {os.getenv('COINBASE_API_PASSPHRASE') is not None}")
logger.info("[NIJA-DEBUG] END runtime import/env check")
# --- End debug block ----------------------------------------------------

# Now import the client (this uses the runtime-detected state above)
try:
    from nija_client import client, USE_DUMMY
except Exception as e:
    logger.error(f"[NIJA] Failed to import client from nija_client: {e}")
    # Re-raise so the container logs show the failure and the process exits
    raise

from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def health_check():
    status = "DummyClient (no live trades)" if USE_DUMMY else "Live CoinbaseClient"
    return jsonify({"status": "ok", "trading_mode": status})

# --- Worker startup (import your worker runner and pass in client) ---
def _start_worker_in_process():
    try:
        from nija_worker import start_worker  # your worker function that accepts client
    except Exception as e:
        logger.error(f"[NIJA] Could not import start_worker from nija_worker: {e}")
        raise

    # Start the worker (this function will run indefinitely in the main process)
    try:
        start_worker(client)
    except Exception as e:
        logger.error(f"[NIJA] start_worker raised an exception: {e}")
        raise

# --- Main entrypoint ---
if __name__ == "__main__":
    if USE_DUMMY:
        logger.warning("[NIJA] Using DummyClient — live trading disabled")
    else:
        logger.info("[NIJA] Using Live CoinbaseClient — live trading enabled")

    # Start worker (blocking) and also run Flask for health check.
    # To keep things simple, start the worker in the main thread and let Flask run as a dev server.
    # If you use a production WSGI server, adapt this to run the worker separately.
    try:
        # Start the worker (blocking). If you want the Flask server to run simultaneously,
        # run worker in a background thread — for clarity we run worker first here.
        _start_worker_in_process()
    except KeyboardInterrupt:
        logger.info("[NIJA] Worker interrupted by user. Exiting.")
    except Exception:
        logger.exception("[NIJA] Worker failed on startup.")

    # Start Flask health check (only reached if worker stops)
    port = int(os.getenv("PORT", 8080))
    logger.info(f"[NIJA] Starting Flask health server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
