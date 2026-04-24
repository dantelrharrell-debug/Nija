import logging
from flask import Flask
from threading import Thread
from typing import Optional, Any
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Environment variables
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")

client: Optional[Any] = None

# --- Coinbase Client Initialization ---
def initialize_coinbase_client() -> Optional[Any]:
    """
    Initialize Coinbase client using ONLY API_KEY and API_SECRET.
    Fully live trading. No passphrase required.
    """
    global client

    if not (API_KEY and API_SECRET):
        logger.warning("Missing COINBASE_API_KEY or COINBASE_API_SECRET. Live trading disabled.")
        client = None
        return None

    # Try coinbase_advanced_py first
    try:
        from coinbase_advanced_py.client import Client as AdvancedClient
        logger.info("coinbase_advanced_py detected. Initializing advanced client...")
        client = AdvancedClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("Advanced Coinbase client initialized successfully. LIVE TRADING ENABLED.")
        return client
    except Exception as e:
        logger.warning(f"coinbase_advanced_py failed: {e}. Falling back to official client...")

    # Fallback → official coinbase client
    try:
        from coinbase.wallet.client import Client as WalletClient
        logger.info("Initializing official Coinbase (wallet) client...")
        client = WalletClient(API_KEY, API_SECRET)
        logger.info("Official Coinbase client initialized successfully. LIVE TRADING ENABLED.")
        return client
    except Exception as e:
        logger.error(f"Official client failed: {e}")

    client = None
    logger.error("Could NOT initialize ANY Coinbase client. LIVE TRADING DISABLED.")
    return None

# --- Flask App ---
def create_app():
    app = Flask(__name__)
    logger.info("Flask app created successfully")

    # Initialize Coinbase client
    initialize_coinbase_client()

    # Start live trading loop in background
    if client:
        try:
            from bot.live_bot_script.live_trading import run_live_trading
            Thread(target=run_live_trading, args=(client,), daemon=True).start()
            logger.info("Live trading thread started successfully.")
        except Exception as e:
            logger.error(f"Failed to start live trading thread: {e}")
    else:
        logger.warning("Client not ready. Live trading NOT started.")

    # Example route
    @app.route("/")
    def home():
        return "NIJA Trading Bot is LIVE!"

    return app

# For running standalone
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000)
