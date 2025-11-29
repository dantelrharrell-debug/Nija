import os
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def create_app():
    """Factory function to create Flask app"""
    app = Flask(__name__)

    # Example health check route
    @app.route("/")
    def home():
        return "NIJA Bot is running!"

    # Optional: initialize Coinbase client safely
    try:
        from cd.vendor.coinbase_advanced_py.client import Client
        COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
        COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
        COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")

        if all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_SUB]):
            client = Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_sub=COINBASE_API_SUB)
            logging.info("Coinbase client initialized!")
            app.coinbase_client = client
        else:
            logging.warning("Coinbase keys missing; client not initialized.")
            app.coinbase_client = None
    except ModuleNotFoundError:
        logging.warning("Coinbase module not found; live trading disabled.")
        app.coinbase_client = None

    return app
