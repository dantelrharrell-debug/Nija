from flask import Flask
import os
import logging

# Attempt to import Coinbase client safely
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.warning("coinbase_advanced module not installed. Live trading disabled.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

def test_coinbase_connection():
    if Client is None:
        logging.warning("Cannot test Coinbase: module not installed")
        return False
    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
        logging.info("Coinbase connection OK")
        return True
    except Exception as e:
        logging.error(f"Coinbase connection failed: {e}")
        return False

# ❌ Do NOT start Flask dev server
if __name__ == "__main__":
    logging.info("Flask dev server disabled in production. Start Gunicorn instead.")
