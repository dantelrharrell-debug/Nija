import logging
import os
from flask import Flask, send_file, abort

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("wsgi")

# Create Flask app
app = Flask(__name__)

# Correct Coinbase client import
try:
    from coinbase_advanced_py.client import Client
except ModuleNotFoundError:
    Client = None
    logger.error("coinbase_advanced_py.client module not found. Ensure coinbase-advanced-py is installed.")

# Load Coinbase credentials from environment
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")

def test_coinbase_connection():
    if Client is None:
        logger.error("Cannot connect: Coinbase client not available.")
        return False
    try:
        client = Client(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            api_sub=COINBASE_API_SUB
        )
        logger.info("Coinbase client initialized successfully!")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
        return False

# Run startup checks
with app.app_context():
    test_coinbase_connection()

@app.route("/")
def index():
    return "Nija Trading Bot is running!"

# Temporary Coinbase debug download endpoint
DEBUG_FILE = "/app/logs/coinbase_module_debug.txt"

@app.route("/debug/coinbase")
def debug_coinbase():
    if not os.path.exists(DEBUG_FILE):
        return "Debug file not yet created. Wait a few seconds and refresh.\n", 404
    try:
        return send_file(DEBUG_FILE, mimetype="text/plain", as_attachment=True, download_name="coinbase_module_debug.txt")
    except Exception as e:
        abort(500, description=str(e))
