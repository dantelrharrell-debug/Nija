import os
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

# --- Coinbase connection check ---
def init_coinbase():
    try:
        from coinbase_advanced.client import Client
    except ModuleNotFoundError:
        logging.error("coinbase_advanced module not installed. Live trading disabled.")
        return None

    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        account = client.get_account()
        logging.info(f"Coinbase connection successful. Account ID: {account['id']}")
        return client
    except Exception as e:
        logging.error(f"Coinbase connection failed: {e}")
        return None

coinbase_client = init_coinbase()
