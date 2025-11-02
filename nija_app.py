import os
import logging
import threading
import time
from decimal import Decimal
from flask import Flask, jsonify

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_app")

# --- Flask app ---
app = Flask(__name__)

# --- Coinbase client ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient unavailable, using dummy")
    CoinbaseClient = None

# --- PEM setup ---
PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
if PEM_CONTENT:
    os.makedirs(os.path.dirname(PEM_PATH), exist_ok=True)
    with open(PEM_PATH, "w") as f:
        f.write(PEM_CONTENT)
    logger.info("[NIJA] PEM written")
else:
    logger.warning("[NIJA] No PEM content in env")

# --- Initialize client ---
client = None
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret_path=PEM_PATH,
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE"),
        )
        logger.info("[NIJA] Coinbase RESTClient initialized")
    except Exception as e:
        logger.error(f"[NIJA] Failed to init CoinbaseClient: {e}")

# --- Balance helper ---
def get_usd_balance(client: CoinbaseClient) -> Decimal:
    if not client:
        return Decimal(0)
    try:
        balances = client.get_spot_account_balances()
        return Decimal(balances.get("USD", {}).get("available", 0))
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed: {e}")
        return Decimal(0)

# --- Worker thread ---
def run_worker():
    logger.info("[NIJA-WORKER] Started")
    while True:
        try:
            usd_balance = get_usd_balance(client)
            if client and usd_balance > 10:
                logger.info(f"[NIJA-WORKER] USD balance: {usd_balance}")
                # Insert your trading logic here
        except Exception as e:
            logger.error(f"[NIJA-WORKER] Exception: {e}")
        time.sleep(10)

# --- Start worker ---
worker_thread = threading.Thread(target=run_worker, daemon=True)
worker_thread.start()
logger.info("[NIJA-APP] Worker thread started")

# --- Flask routes ---
@app.route("/")
def index():
    return jsonify({
        "status": "Nija Trading Bot Online",
        "USD_balance": str(get_usd_balance(client))
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200
