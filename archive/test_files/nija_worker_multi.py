# nija_worker_multi.py
import os
import logging
import threading
import time
from decimal import Decimal

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker_multi")

# --- Attempt Coinbase import ---
try:
    
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient unavailable, using dummy")
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
    logger.warning("[NIJA] No PEM content found in env, dummy mode active")

# --- Initialize Coinbase client ---
client = None
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret_path=PEM_PATH,
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE"),
        )
        logger.info("[NIJA] Coinbase client initialized")
    except Exception as e:
        logger.error(f"[NIJA] Failed to init CoinbaseClient: {e}")

# --- Helper: fetch all balances ---
def get_all_balances(client: CoinbaseClient):
    """Returns dict of {currency: available} balances or dummy if client is None."""
    if client is None:
        # dummy data
        return {"USD": Decimal(0), "BTC": Decimal(0), "ETH": Decimal(0)}
    try:
        raw = client.get_spot_account_balances()  # returns {currency: {available, hold, total}}
        balances = {cur: Decimal(info.get("available", 0)) for cur, info in raw.items()}
        return balances
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch balances: {e}")
        return {"USD": Decimal(0)}

# --- Background worker ---
def run_worker():
    logger.info("[NIJA-WORKER] Starting multi-coin worker loop...")
    while True:
        try:
            balances = get_all_balances(client)
            usd = balances.get("USD", Decimal(0))
            logger.info(f"[NIJA] Current balances: {balances}")
            
            # --- Example trade logic ---
            if client:
                if usd >= 10:
                    logger.info("[NIJA] Conditions met to consider a trade...")
                    # insert your trade logic here
        except Exception as e:
            logger.error(f"[NIJA-WORKER] Exception in worker: {e}")
        time.sleep(10)  # loop interval

# --- Start thread ---
worker_thread = threading.Thread(target=run_worker, daemon=True)
worker_thread.start()
logger.info("[NIJA-WORKER] Worker thread started")
