# web/wsgi.py
import logging
import os
from flask import Flask

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Try importing Coinbase client
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced.client module not found. Ensure coinbase-advanced-py is installed.")

# Load Coinbase credentials from environment
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")

def test_coinbase_connection():
    if Client is None:
        logging.error("Cannot connect: Coinbase client not available.")
        return False
    try:
        client = Client(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            api_sub=COINBASE_API_SUB
        )
        logging.info("Coinbase client initialized successfully!")
        return True
    except Exception as e:
        logging.error(f"Failed to initialize Coinbase client: {e}")
        return False

# Create Flask app
app = Flask(__name__)

# Run startup checks immediately
with app.app_context():
    test_coinbase_connection()

@app.route("/")
def index():
    return "Nija Bot Running!"
