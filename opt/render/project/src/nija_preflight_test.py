import logging
from nija_coinbase_client import get_usd_balance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_preflight_test")

logger.info("[NIJA-PREFLIGHT] Starting one-shot preflight test (JWT -> accounts)...")
bal = get_usd_balance()
logger.info("[NIJA-PREFLIGHT] Preflight result: USD balance = %s", bal)
print("PREFLIGHT_BALANCE=" + str(bal))
