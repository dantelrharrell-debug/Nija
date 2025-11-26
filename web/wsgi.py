# web/wsgi.py
import os
import logging
from flask import Flask, send_file, abort

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("wsgi")

app = Flask(__name__)

# Debug file written by start_all.sh (if any)
DEBUG_FILE = "/app/logs/coinbase_module_debug.txt"

@app.route("/")
def index():
    return "Nija Trading Bot is running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    if not os.path.exists(DEBUG_FILE):
        return "Debug file not yet created. Wait a few seconds and refresh.\n", 404
    try:
        return send_file(DEBUG_FILE, mimetype="text/plain", as_attachment=True, download_name="coinbase_module_debug.txt")
    except Exception as e:
        abort(500, description=str(e))
