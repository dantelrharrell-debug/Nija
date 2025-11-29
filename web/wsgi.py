# web/wsgi.py
from flask import Flask
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

# Example route to verify server is running
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
    else:
        client = None
        logging.warning("Coinbase keys missing; client not initialized.")
except ModuleNotFoundError:
    client = None
    logging.warning("Coinbase module not found; live trading disabled.")
