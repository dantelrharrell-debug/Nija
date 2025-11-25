# main.py
import os
import sys
import logging
import threading
import traceback
from flask import Flask, request, jsonify

# --- Logging setup ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("nija")

# --- Environment quick-checks ---
live_mode = os.getenv("LIVE_TRADING", "0")
if live_mode == "1":
    logger.info("✅ LIVE_TRADING is ACTIVE")
else:
    logger.warning("⚠️ LIVE_TRADING is NOT active! Set LIVE_TRADING=1 if you intend to trade live.")

# Print interpreter diagnostics (helpful for debugging ModuleNotFoundError)
logger.info("Python executable: %s", sys.executable)
logger.info("sys.path (first 6): %s", sys.path[:6])

# Use python -m pip to list installed packages for the same interpreter
try:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "list"], check=False)
except Exception:
    logger.exception("Failed to run pip list")

# --- Coinbase client import with diagnostics & graceful fallback ---
CoinbaseClient = None
_coinbase_import_ok = False

def _coinbase_import_diagnostics(exc):
    try:
        import pkgutil
        mods = [m.name for m in pkgutil.iter_modules() if "coinbase" in m.name.lower()]
    except Exception:
        mods = []
    logger.error("coinbase import failed: %s", exc)
    logger.error("traceback: %s", traceback.format_exc())
    logger.error("coinbase-like modules visible: %s", mods)
    logger.error("sys.executable: %s", sys.executable)
    logger.error("sys.path (first 10): %s", sys.path[:10])

try:
    # Try the preferred client import
    from nija_client import CoinbaseClient as _CoinbaseClient  # your client wrapper
    CoinbaseClient = _CoinbaseClient
    _coinbase_import_ok = True
    logger.info("✅ Imported nija_client.CoinbaseClient successfully.")
except Exception as e:
    _coinbase_import_diagnostics(e)
    # Keep CoinbaseClient as None so the app still starts and exposes endpoints
    CoinbaseClient = None

# --- Test function to verify Coinbase connectivity at runtime ---
def test_coinbase_connection_instance(client_instance):
    """
    Use the client instance to verify connection. This function assumes
    your client implements a lightweight call like `list_accounts()` or `fetch_accounts()`.
    Adjust to match your client's API.
    """
    try:
        # Try common method names in order to be flexible
        for method_name in ("fetch_accounts", "list_accounts", "accounts", "get_accounts"):
            if hasattr(client_instance, method_name):
                fn = getattr(client_instance, method_name)
                result = fn()
                logger.info("✅ Coinbase check OK via %s. Result sample: %s", method_name, str(result)[:400])
                return True
        # If no known method, at least try str() to ensure client constructed
        logger.info("Coinbase client constructed (no known list method). repr: %s", repr(client_instance)[:400])
        return True
    except Exception as e:
        logger.exception("Coinbase client call failed: %s", e)
        return False

def create_coinbase_client_or_none():
    """Construct a CoinbaseClient if import succeeded; return None and log diagnostics otherwise."""
    if not CoinbaseClient:
        logger.warning("CoinbaseClient not available (import failed).")
        return None
    try:
        client = CoinbaseClient()  # adapt if you need to pass API keys/envs explicitly
        ok = test_coinbase_connection_instance(client)
        if not ok:
            logger.warning("Coinbase client created but connectivity check failed.")
        return client
    except Exception as e:
        logger.exception("Failed to instantiate CoinbaseClient: %s", e)
        return None

# Create Flask app
app = Flask(__name__)

# Initialize client at import time (safe fallback if it fails)
client = create_coinbase_client_or_none()

# --- Flask routes ---
@app.route("/")
def index():
    status = {
        "service": "NIJA Bot",
        "coinbase_client": "initialized" if client else "not-initialized",
        "live_trading": live_mode == "1"
    }
    return jsonify(status)

@app.route("/accounts")
def accounts():
    if not client:
        return jsonify({"error": "coinbase client not initialized"}), 500
    try:
        # Try common method names
        for method_name in ("list_accounts", "fetch_accounts", "accounts", "get_accounts"):
            if hasattr(client, method_name):
                accts = getattr(client, method_name)()
                return jsonify({"accounts": accts})
        return jsonify({"error": "client has no account listing method"}), 500
    except Exception as e:
        logger.exception("Failed fetching accounts: %s", e)
        return jsonify({"error": str(e)}), 500

# TradingView webhook route
@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    try:
        payload = request.get_json(force=True, silent=True) or request.json or {}
        logger.info("Received TradingView webhook: %s", payload)
        # call a handler - make sure it is defensive and non-blocking
        try:
            # Attempt to import the handler lazily so import failures don't break the app
            from tv_webhook_listener import handle_tv_webhook
            # If the handler might be slow, consider pushing to a background thread / queue
            threading.Thread(target=handle_tv_webhook, args=(payload,), daemon=True).start()
        except Exception as e:
            logger.exception("Failed to dispatch to handle_tv_webhook: %s", e)
            # fallback: just log the payload for manual handling
        return jsonify({"status": "received"}), 200
    except Exception as e:
        logger.exception("Failed handling TradingView webhook: %s", e)
        return jsonify({"error": str(e)}), 500

# --- Optional: Start background trading loop (if you have coinbase_loop) ---
def start_coinbase_loop_if_possible():
    try:
        from coinbase_trader import coinbase_loop
    except Exception as e:
        logger.warning("coinbase_trader.coinbase_loop not available: %s", e)
        return None

    if client is None:
        logger.warning("Not starting trading loop because Coinbase client is not initialized.")
        return None

    try:
        t = threading.Thread(target=coinbase_loop, args=(client,), daemon=True)
        t.start()
        logger.info("Started Coinbase trading loop thread.")
        return t
    except Exception as e:
        logger.exception("Failed to start coinbase trading loop: %s", e)
        return None

# If running directly (not via gunicorn), start loop and Flask dev server
if __name__ == "__main__":
    start_coinbase_loop_if_possible()
    port = int(os.getenv("PORT", 5000))
    logger.info("Starting Flask dev server on port %s", port)
    app.run(host="0.0.0.0", port=port, debug=os.getenv("DEBUG", "0") == "1")
