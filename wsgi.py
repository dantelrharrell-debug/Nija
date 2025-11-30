# wsgi.py
import os
import logging
import threading
import time
from flask import Flask, jsonify
from nija_client import get_coinbase_client, start_bot  # Make sure nija_client.py exposes these

# ------------------------------
# Logging
# ------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ------------------------------
# Flask App
# ------------------------------
app = Flask(__name__)

# ------------------------------
# Coinbase Client
# ------------------------------
PEM = os.environ.get("COINBASE_PEM_CONTENT")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

client = get_coinbase_client(pem=PEM, org_id=ORG_ID)

# ------------------------------
# Routes
# ------------------------------
@app.route("/")
def home():
    return "🚀 NIJA Bot is online and running!"

@app.route("/status")
def status():
    return jsonify({
        "status": "running",
        "bot_available": start_bot is not None,
        "environment": os.environ.get("RAILWAY_ENVIRONMENT", "unknown")
    })

@app.route("/accounts")
def accounts():
    try:
        accounts = client.get_accounts()
        return jsonify(accounts)
    except Exception as e:
        logging.error(f"Failed to fetch accounts: {e}")
        return jsonify({"error": str(e)}), 500

# ------------------------------
# Background Bot Loop
# ------------------------------
def bot_loop():
    """
    Launches the NIJA bot and keeps the loop alive
    """
    if start_bot is None:
        logging.warning("start_bot() not found, skipping bot loop")
        return

    logging.info("Starting NIJA Bot loop in background thread...")
    try:
        start_bot()  # This should block / handle trading logic internally
    except Exception as e:
        logging.exception(f"NIJA Bot crashed: {e}")

# Start bot loop in a separate thread (daemon = won't block shutdown)
threading.Thread(target=bot_loop, daemon=True).start()

# ------------------------------
# Run Flask (for local testing)
# ------------------------------
if __name__ == "__main__":
    logging.info("Starting Flask server for NIJA Bot...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
    
