from flask import Flask, jsonify, request
import logging
import os
import sys

# Keep vendor path as fallback if you include vendor/coinbase_advanced_py in repo
sys.path.append(os.path.join(os.path.dirname(__file__), "../vendor/coinbase_advanced_py"))

# Try multiple import paths for the Coinbase client package to be resilient
Client = None
_import_errors = {}

try:
    from coinbase_advanced_py.client import Client as _Client
    Client = _Client
    COINBASE_AVAILABLE = True
except Exception as e:
    _import_errors["coinbase_advanced_py"] = repr(e)
    try:
        from coinbase_advanced.client import Client as _Client2
        Client = _Client2
        COINBASE_AVAILABLE = True
    except Exception as e2:
        _import_errors["coinbase_advanced"] = repr(e2)
        logging.warning(
            "⚠️ Coinbase client not present or failed to import; live trading disabled. Import errors: %s",
            _import_errors
        )
        COINBASE_AVAILABLE = False

# Flask app
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Health check
@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

# Safe blueprint registration (use helper)
try:
    from web.register_tradingview import try_register_tradingview
    try_register_tradingview(app)
except Exception:
    logging.exception("Unexpected error while trying to register TradingView blueprint")

# Minimal live Coinbase connection check
def init_coinbase():
    if not COINBASE_AVAILABLE or Client is None:
        return None

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_sub = os.getenv("COINBASE_API_SUB")

    if not all([api_key, api_secret, api_sub]):
        logging.warning("⚠️ Coinbase API credentials missing, skipping live setup")
        return None

    try:
        client = Client(api_key, api_secret, api_sub)
        accounts = client.get_accounts()  # test connection
        logging.info(f"✅ Coinbase connection OK, accounts: {accounts}")
        return client
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return None

coinbase_client = init_coinbase()

# Trade status endpoint
@app.route("/trade/status", methods=["GET"])
def trade_status():
    if not coinbase_client:
        return jsonify({"status": "Coinbase not connected"}), 503
    try:
        accounts = coinbase_client.get_accounts()
        return jsonify({"status": "live", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
