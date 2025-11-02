# nija_preflight.py
import logging
from nija_client import get_usd_balance

logger = logging.getLogger("nija_preflight")

def run_preflight():
    logger.info("[NIJA-PREFLIGHT] Checking live Coinbase connection...")
    balance = get_usd_balance()
    if balance > 0:
        logger.info(f"[NIJA-PREFLIGHT] ✅ Connection OK - USD Balance: {balance}")
    else:
        logger.warning(f"[NIJA-PREFLIGHT] ⚠️ Connection OK but no USD funds available.")
