# main.py
import os
import logging
from flask import Flask, jsonify
from nija_client import get_coinbase_client  # Your robust factory from before

# ----------------------------
# Logging Setup
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------
# Flask App Setup
# ----------------------------
app = Flask(__name__)

@app.route("/__health__", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"}), 200

@app.route("/start", methods=["POST"])
def start_trading_endpoint():
    """Endpoint to trigger trading"""
    try:
        start_trading()
        return jsonify({"status": "trading started"}), 200
    except Exception as e:
        logger.exception("Error starting trading: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500

# ----------------------------
# Coinbase Client Initialization
# ----------------------------
def init_coinbase_client():
    """
    Instantiates a real Coinbase Advanced client using environment variables.
    Falls back to MockClient if SDK missing or misconfigured.
    """
    try:
        client = get_coinbase_client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            pem_content=os.environ.get("COINBASE_PEM_CONTENT"),
            org_id=os.environ.get("COINBASE_ORG_ID")
        )
        # Quick test: list accounts to verify connectivity
        accounts = client.list_accounts()
        logger.info("Coinbase client initialized. Accounts: %s", accounts)
        return client
    except Exception as e:
        logger.exception("Failed to initialize Coinbase client: %s", e)
        return get_coinbase_client()  # fallback MockClient

# Global client instance
client = init_coinbase_client()

# ----------------------------
# Trading Logic
# ----------------------------
def start_trading():
    """
    Example trading logic. Add your real trading strategy here.
    """
    if not client:
        raise RuntimeError("Coinbase client not initialized")

    # Fetch accounts
    accounts = client.list_accounts()
    logger.info("Accounts fetched for trading: %s", accounts)

    # Example placeholder: print balances
    for acct in accounts:
        logger.info("Account: %s, Balance: %s", acct.get("id"), acct.get("balance"))

    # TODO: Replace with your actual order placement logic
    logger.info("Trading logic executed (replace with real strategy)")

# ----------------------------
# WSGI auto-expose for Gunicorn
# ----------------------------
def _expose_wsgi_app():
    """
    Ensures 'app' callable is visible for Gunicorn.
    """
    module_globals = globals()
    if "app" not in module_globals:
        logger.warning("No top-level 'app' found; exposing minimal health-check app.")
        fallback = Flask("fallback_app")
        @fallback.route("/__health__", methods=["GET"])
        def fallback_health():
            return jsonify({"status": "fallback-ok"}), 200
        module_globals["app"] = fallback

try:
    _expose_wsgi_app()
except Exception as e:
    logger.exception("Error running WSGI shim: %s", e)

# ----------------------------
# Entry point for local testing
# ----------------------------
if __name__ == "__main__":
    logger.info("Starting local Flask server on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
