# nija_railway_preflight.py
from nija_coinbase_client import get_usd_balance
import logging

logging.basicConfig(level=logging.INFO)
logging.info("[NIJA-PREFLIGHT] Starting Coinbase JWT preflight check...")

try:
    bal = get_usd_balance()
    logging.info("[NIJA-PREFLIGHT] USD balance fetched successfully: %s", bal)
    if bal <= 0:
        logging.warning("[NIJA-PREFLIGHT] USD balance is zero or unavailable — check funding or permissions.")
except Exception as e:
    logging.error("[NIJA-PREFLIGHT] Failed to fetch balance: %s", e)
    raise SystemExit("[NIJA-PREFLIGHT] Preflight failed")

logging.info("[NIJA-PREFLIGHT] Preflight check complete ✅")
