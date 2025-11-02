# nija_web_worker.py
import logging
from flask import Flask, jsonify
from nija_render_worker import run_worker, client, usd_balance

# --- Logging setup ---
logger = logging.getLogger("nija_web_worker")
logger.setLevel(logging.INFO)

# --- Flask app ---
app = Flask(__name__)

@app.route("/")
def index():
    balance = usd_balance if usd_balance is not None else 0
    return jsonify({
        "status": "Nija Trading Bot Online",
        "USD_balance": str(balance)
    })

# --- Optional health check ---
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

# --- Start background worker ---
import threading
worker_thread = threading.Thread(target=run_worker, daemon=True)
worker_thread.start()

logger.info("[NIJA-WEB] Flask app initialized, worker thread started.")
