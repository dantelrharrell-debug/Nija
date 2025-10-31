# nija_preflight.py
import logging
from nija_coinbase_client import get_usd_balance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

# Attempt to fetch USD balance via REST only
bal = get_usd_balance()
logger.info("[NIJA-PREFLIGHT] USD balance fetched successfully: %s", bal)

if bal is None or bal == 0:
    logger.warning("[NIJA-PREFLIGHT] USD balance is zero or unavailable — check funding or permissions.")
    logger.warning("[NIJA-PREFLIGHT] Preflight complete, but some checks failed. Resolve errors before going live.")
else:
    logger.info("[NIJA-PREFLIGHT] Preflight check passed. USD balance: %s", bal)
