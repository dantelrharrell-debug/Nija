# nija_render_worker.py
import logging
from nija_client import init_client
from nija_balance_helper import get_usd_balance

logger = logging.getLogger("nija_render_worker")
logger.setLevel(logging.INFO)

# --- Initialize client ---
client = init_client()

# --- Fetch USD balance ---
usd_balance = get_usd_balance(client)
logger.info(f"[NIJA] Starting worker with USD balance: {usd_balance}")

def run_worker():
    logger.info("[NIJA] Worker running...")
    # your main loop here, pass `client` wherever needed
    while True:
        try:
            balance = get_usd_balance(client)
            logger.info(f"[NIJA] Current USD balance: {balance}")
            # ...rest of trading logic...
        except Exception as e:
            logger.error(f"[NIJA] Worker loop error: {e}")
