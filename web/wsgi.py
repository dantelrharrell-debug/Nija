# web/wsgi.py
from flask import Flask, jsonify
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add vendor path if you vendor the coinbase client (optional)
sys.path.append(os.path.join(os.path.dirname(__file__), "../vendor/coinbase_advanced_py"))

LIVE_TRADING = os.getenv("LIVE_TRADING", "0").strip() in ("1", "true", "True", "yes", "YES")

try:
    from coinbase_advanced_py.client import Client as CoinbaseClient
    COINBASE_MODULE_AVAILABLE = True
except Exception:
    logger.warning("⚠️ Coinbase client not found — live trading disabled.")
    COINBASE_MODULE_AVAILABLE = False

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

def init_coinbase():
    """
    If LIVE_TRADING is enabled we require credentials and the client to be present.
    If LIVE_TRADING is disabled, we don't attempt to create a live client.
    """
    if not LIVE_TRADING:
        logger.info("LIVE_TRADING disabled (safe). Coinbase client will not be initialized.")
        return None

    if not COINBASE_MODULE_AVAILABLE:
        logger.error("LIVE_TRADING=1 but Coinbase client library is missing.")
        raise RuntimeError("Coinbase client missing while LIVE_TRADING=1")

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_sub = os.getenv("COINBASE_API_SUB")

    if not all([api_key, api_secret, api_sub]):
        logger.error("LIVE_TRADING=1 but some Coinbase API credentials are missing.")
        raise RuntimeError("Missing Coinbase API credentials while LIVE_TRADING=1")

    try:
        client = CoinbaseClient(api_key, api_secret, api_sub)
        # Minimal connectivity check (you can remove for speed)
        _ = client.get_accounts()
        logger.info("✅ Coinbase connection initialized.")
        return client
    except Exception as e:
        logger.exception("❌ Coinbase connection failed during init.")
        raise

# Initialize coinbase only if LIVE_TRADING set
try:
    coinbase_client = init_coinbase()
except Exception as e:
    # Fail fast during container start if live trading requested and can't initialize
    logger.error("Exiting due to Coinbase init failure with LIVE_TRADING enabled.")
    raise

# Register tradingview blueprint (import from module that defines it)
try:
    # adjust import path to where you placed the blueprint file
    from web.tradingview_webhook import bp as tradingview_bp
    app.register_blueprint(tradingview_bp, url_prefix="/tv")
    logger.info("✅ TradingView blueprint registered at /tv")
except Exception as e:
    logger.warning(f"⚠️ Could not register TradingView blueprint: {e}")
