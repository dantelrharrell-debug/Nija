import logging
import os
from flask import Flask, send_file, abort

# ----------------------
# Setup logging
# ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("wsgi")

# ----------------------
# Create Flask app
# ----------------------
app = Flask(__name__)

# ----------------------
# Coinbase setup
# ----------------------
try:
    from coinbase_advanced_py.client import Client
except ModuleNotFoundError:
    Client = None
    logger.error("coinbase_advanced_py.client module not found. Ensure coinbase-advanced-py is installed.")
except AttributeError:
    Client = None
    logger.error("Coinbase Client class not found in coinbase_advanced_py.client")

# Load Coinbase credentials from environment
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")

# Debug file path
DEBUG_FILE = "/app/logs/coinbase_module_debug.txt"

# ----------------------
# Test Coinbase connection safely
# ----------------------
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
        # Optional: write debug info
        os.makedirs(os.path.dirname(DEBUG_FILE), exist_ok=True)
        with open(DEBUG_FILE, "w") as f:
            f.write(f"Coinbase client initialized: {client}\n")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
        # Write error to debug file
        os.makedirs(os.path.dirname(DEBUG_FILE), exist_ok=True)
        with open(DEBUG_FILE, "w") as f:
            f.write(f"Coinbase init error: {e}\n")
        return False

# Run startup check safely
with app.app_context():
    success = test_coinbase_connection()
    if not success:
        logger.warning("Coinbase client failed, but Flask app will continue running.")

# ----------------------
# Routes
# ----------------------
@app.route("/")
def index():
    return "Nija Trading Bot is running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    if not os.path.exists(DEBUG_FILE):
        return "Debug file not yet created. Wait a few seconds and refresh.\n", 404
    try:
        return send_file(
            DEBUG_FILE,
            mimetype="text/plain",
            as_attachment=True,
            download_name="coinbase_module_debug.txt"
        )
    except Exception as e:
        abort(500, description=str(e))
