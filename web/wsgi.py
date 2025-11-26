# web/wsgi.py
import os
import logging
from flask import Flask, send_file, abort

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")

app = Flask(__name__)

# debug file path (will be created by nija_client on failures)
DEBUG_FILE = "/app/logs/coinbase_module_debug.txt"

# Import safe test function
from nija_client import test_coinbase_connection  # safe: won't raise on import

# Run test but never exit container if test fails
with app.app_context():
    ok = test_coinbase_connection()
    if not ok:
        logger.warning("Coinbase connection test failed at startup. App will continue; check /debug/coinbase for details.")

@app.route("/")
def index():
    return "Nija Trading Bot is running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    # Serve debug file if present
    if not os.path.exists(DEBUG_FILE):
        return "Debug file not present yet. Check logs.\n", 404
    try:
        return send_file(DEBUG_FILE, mimetype="text/plain", as_attachment=True, download_name="coinbase_module_debug.txt")
    except Exception as e:
        abort(500, description=str(e))
