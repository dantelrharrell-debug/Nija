# nija_startup.py
import os
import sys
import logging
from decimal import Decimal
import time

from nija_client import init_client  # Updated client with DummyClient fallback

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("nija_startup")

# --- Initialize client ---
client = init_client()

# --- Pre-flight validation ---
if client.__class__.__name__ == "DummyClient":
    logger.error("[NIJA] Coinbase credentials invalid or missing. Exiting startup.")
    sys.exit(1)

try:
    accounts = client.get_accounts()
    usd_balance = next((Decimal(a["balance"]) for a in accounts if a["currency"] == "USD"), Decimal("0"))
    logger.info(f"[NIJA] Pre-flight check passed. USD Balance: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA] Pre-flight balance fetch failed: {e}")
    sys.exit(1)

# --- Worker loop ---
logger.info("[NIJA] Starting Nija Trading Bot...")

while True:
    try:
        # Fetch current USD balance
        accounts = client.get_accounts()
        usd_balance = next((Decimal(a["balance"]) for a in accounts if a["currency"] == "USD"), Decimal("0"))
        logger.info(f"[NIJA] Current USD balance: {usd_balance}")

        # --- Call your trading logic here ---
        # from trading_logic import decide_trade
        # decide_trade(client, usd_balance)

        # Sleep or schedule next iteration
        time.sleep(10)

    except Exception as e:
        logger.warning(f"[NIJA-DEBUG] Worker caught exception: {e}")
        time.sleep(5)
