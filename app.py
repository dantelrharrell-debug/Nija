# app.py
import logging
import os
import traceback
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

COINBASE_AVAILABLE = False
COINBASE_IMPORT_ERROR = None
COINBASE_IMPORT_PATH = None

def try_coinbase_import():
    global COINBASE_AVAILABLE, COINBASE_IMPORT_ERROR, COINBASE_IMPORT_PATH
    # Try multiple possible import paths (tolerant)
    candidates = [
        "coinbase_advanced.client",
        "coinbase_advanced",
        "coinbase_advanced_py.client",
        "coinbase.client",
    ]
    for c in candidates:
        try:
            module = __import__(c, fromlist=["*"])
            COINBASE_AVAILABLE = True
            COINBASE_IMPORT_PATH = c
            logging.info("Coinbase import successful from path: %s", c)
            return True
        except Exception as e:
            logging.info("Coinbase import attempt %s failed: %s", c, e)
    COINBASE_AVAILABLE = False
    COINBASE_IMPORT_ERROR = traceback.format_exc()
    return False

# Attempt import at startup (non-fatal)
try_coinbase_import()

@app.route("/")
def index():
    return f"Nija Bot Running! Coinbase module loaded: {COINBASE_AVAILABLE} (path: {COINBASE_IMPORT_PATH})"

@app.route("/debug/coinbase")
def debug_coinbase():
    return jsonify({
        "coinbase_available": COINBASE_AVAILABLE,
        "coinbase_import_path": COINBASE_IMPORT_PATH,
        "coinbase_import_error_snippet": (COINBASE_IMPORT_ERROR or "")[:1000]
    })

@app.route("/debug/env")
def debug_env():
    return jsonify({
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        "FLASK_ENV": os.environ.get("FLASK_ENV"),
        "GUNICORN_CMD_ARGS": os.environ.get("GUNICORN_CMD_ARGS")
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
