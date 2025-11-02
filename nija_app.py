# nija_app.py
import os
import logging
import threading
import time
from decimal import Decimal

from flask import Flask, jsonify

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# --- Coinbase client initialization ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient unavailable, using dummy client")
    CoinbaseClient = None

# --- Helper: write PEM if provided ---
PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")

if PEM_CONTENT:
    os.makedirs(os.path.dirname(PEM_PATH), exist_ok=True)
    with open(PEM_PATH, "w") as f:
        f.write(PEM_CONTENT)
    logger.info("[NIJA] PEM file written successfully")
else:
    logger.warning("[NIJA] No PEM content found in env")

# --- Initialize client ---
client = None
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret_path=PEM_PATH,
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE"),
        )
        logger.info("[NIJA] Coinbase RESTClient initialized successfully")
    except Exception as e:
        logger.error(f"[NIJA] Failed to init CoinbaseClient: {e}")

# --- Balance helper ---
def get_usd_balance(client: CoinbaseClient) -> Decimal:
    if client is None:
        return Decimal(0)
    try:
        balances = client.get_spot_account_balances()
        usd = Decimal(balances.get("USD", {}).get("available", 0))
        return usd
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch USD balance: {e}")
        return Decimal(0)

usd_balance = get_usd_balance(client)

# --- Background trading worker ---
def run_worker():
    global usd_balance
    logger.info("[NIJA-WORKER] Starting trading worker loop...")
    while True:
        try:
            usd_balance = get_usd_balance(client)
            # --- Example trade logic ---
            if client and usd_balance > 10:
                logger.info("[NIJA-WORKER] Checking trade conditions...")
                # You can integrate your trade logic here
        except Exception as e:
            logger.error(f"[NIJA-WORKER] Exception in worker: {e}")
        time.sleep(10)  # adjust loop interval

# --- Flask app ---
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({
        "status": "Nija Trading Bot Online",
        "USD_balance": str(usd_balance)
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

# --- Start background worker thread ---
worker_thread = threading.Thread(target=run_worker, daemon=True)
worker_thread.start()
logger.info("[NIJA-APP] Worker thread started, Flask app ready.")
