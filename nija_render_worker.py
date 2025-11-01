# nija_render_worker.py
import logging
import time
from nija_client import init_client
from nija_balance_helper import get_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

# Initialize the Coinbase client
client = init_client()  # uses coinbase_advanced_py.client.CoinbaseClient if available

# --- Preflight check ---
logger.info("[NIJA-PREFLIGHT] Starting preflight check...")
usd_balance = get_usd_balance()
logger.info(f"[NIJA-PREFLIGHT] USD balance fetched: {usd_balance}")
logger.info("[NIJA-PREFLIGHT] Preflight balance fetch OK.")

# --- Main loop ---
logger.info("[NIJA] Entering main loop. Worker is live (or in simulated mode).")

try:
    while True:
        # Fetch and log periodic USD balance
        usd_balance = get_usd_balance()
        logger.info(f"[NIJA] Periodic USD balance: {usd_balance}")
        
        # --- Here you can place your trading logic ---
        # decide_trade(usd_balance, client, other_params)
        
        time.sleep(10)  # adjust interval as needed

except KeyboardInterrupt:
    logger.info("[NIJA] Worker terminated by user.")

except Exception as e:
    logger.error(f"[NIJA] Worker encountered an error: {e}")
