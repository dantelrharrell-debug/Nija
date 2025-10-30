import sys
import logging
from decimal import Decimal
from nija_client import client, get_usd_balance
from nija_worker import run_worker

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_startup")

# --- Pre-flight validation ---
try:
    accounts = client.get_accounts()
    usd_balance = next((Decimal(a["balance"]) for a in accounts if a["currency"] == "USD"), None)
    if usd_balance is None:
        raise Exception("No USD account found")
    logger.info(f"[NIJA] Pre-flight check passed. USD Balance: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA] Coinbase credentials invalid or API call failed: {e}")
    sys.exit(1)

# --- Start the live trading worker ---
logger.info("[NIJA] Starting Nija Trading Bot (LIVE mode)")
try:
    run_worker()
except KeyboardInterrupt:
    logger.info("[NIJA] Worker stopped by user")
except Exception as e:
    logger.error(f"[NIJA] Unexpected error in worker: {e}")
    sys.exit(1)
