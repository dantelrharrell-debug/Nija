# app/__init__.py
import os
import logging
from flask import Flask

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def init_coinbase_client(app):
    # read env vars
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE")  # your logs mention this
    # optional: COINBASE_API_SUB etc.
    missing = [name for name, val in [
        ("COINBASE_API_KEY", api_key),
        ("COINBASE_API_SECRET", api_secret),
        ("COINBASE_API_PASSPHRASE", api_passphrase),
    ] if not val]

    if missing:
        logger.warning("Missing environment variables: %s", ", ".join(missing))
        logger.warning("Coinbase client not initialized due to missing credentials.")
        return None

    # Try importing coinbase_advanced_py then fallback to official client
    try:
        from coinbase_advanced_py.client import Client as AdvancedClient
        logger.info("coinbase_advanced_py imported successfully.")
        client = AdvancedClient(api_key=api_key, api_secret=api_secret, passphrase=api_passphrase)
        return client
    except Exception as e:
        logger.info("coinbase_advanced_py not available or failed to init: %s", e)
        # fallback
        try:
            from coinbase.wallet.client import Client as OfficialClient
            logger.info("Official coinbase Client initialized (fallback).")
            client = OfficialClient(api_key, api_secret)
            return client
        except Exception as e2:
            logger.error("Official Coinbase client failed to initialize: %s", e2)
            return None

def create_app(config_object=None):
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    if config_object:
        app.config.from_object(config_object)

    # Initialize Coinbase client and attach to app for later use
    app.coinbase_client = init_coinbase_client(app)

    # Simple health route
    @app.route("/healthz")
    def health():
        cb_status = "initialized" if app.coinbase_client else "no-coinbase-client"
        return {"status": "ok", "coinbase": cb_status}, 200

    return app
