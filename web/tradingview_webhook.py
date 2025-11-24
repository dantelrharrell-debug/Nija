from flask import Flask, jsonify, request
import logging
import os
import sys

# --- Add vendor path for Coinbase client ---
sys.path.append(os.path.join(os.path.dirname(__file__), "../vendor/coinbase_advanced_py"))

try:
    from coinbase_advanced_py.client import Client
    COINBASE_AVAILABLE = True
except ImportError:
    logging.warning("⚠️ Coinbase client not found, live trading disabled")
    COINBASE_AVAILABLE = False

# --- Flask app ---
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Health check endpoint ---
@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

# --- TradingView webhook blueprint ---
try:
    # Import the blueprint from the module that actually defines it to avoid
    # circular imports / shim mismatches.
    from src.trading.tradingview_webhook import tradingview_blueprint
    app.register_blueprint(tradingview_blueprint, url_prefix="/tv")
    logging.info("✅ TradingView blueprint registered")
    # Export bp for compatibility with imports
    bp = tradingview_blueprint
except Exception as e:
    logging.warning(f"⚠️ Could not register TradingView blueprint: {e}")
    bp = None

# --- Minimal live Coinbase connection check ---
def init_coinbase():
    if not COINBASE_AVAILABLE:
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

# --- Example live endpoint ---
@app.route("/trade/status", methods=["GET"])
def trade_status():
    if not coinbase_client:
        return jsonify({"status": "Coinbase not connected"}), 503
    try:
        accounts = coinbase_client.get_accounts()
        return jsonify({"status": "live", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
