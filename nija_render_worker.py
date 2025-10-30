# nija_render_worker.py
import logging
from decimal import Decimal
import sys
from nija_client import init_client  # Uses the updated client with DummyClient fallback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

# --- Pre-flight check ---
client = init_client()

# Check if the client is a DummyClient (meaning keys failed)
if client.__class__.__name__ == "DummyClient":
    logger.error("[NIJA] Coinbase credentials invalid or missing. Worker cannot start live trading.")
    sys.exit(1)

# Try fetching balances as a final pre-flight test
try:
    accounts = client.get_accounts()
    usd_balance = next((Decimal(a["balance"]) for a in accounts if a["currency"] == "USD"), Decimal("0"))
    logger.info(f"[NIJA] Pre-flight check passed. USD Balance: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA] Pre-flight balance fetch failed: {e}")
    sys.exit(1)

# --- Worker loop ---
logger.info("[NIJA] Starting Nija Trading Bot...")
def run_worker():
    while True:
        try:
            # --- Example: fetch USD balance safely ---
            usd_balance = 0
            accounts = client.get_accounts()
            for acc in accounts:
                if acc.get("currency") == "USD":
                    usd_balance = Decimal(acc.get("balance", "0"))
            logger.info(f"[NIJA] Current USD balance: {usd_balance}")
            
            # --- Call your trading logic here ---
            # decide_trade(client, usd_balance)
            
            # --- Example delay, replace with actual scheduler ---
            import time
            time.sleep(10)

        except Exception as e:
            logger.warning(f"[NIJA-DEBUG] Worker caught exception: {e}")
            # Optional: sleep briefly to prevent log spam
            import time
            time.sleep(5)

if __name__ == "__main__":
    run_worker()
