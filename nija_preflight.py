import logging
from nija_coinbase_client import get_usd_balance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")
usd_balance = get_usd_balance()
logger.info("[NIJA-PREFLIGHT] USD balance fetched: $%s", usd_balance)

if usd_balance == 0:
    logger.warning("[NIJA-PREFLIGHT] USD balance is zero or unavailable — check funding or permissions.")
else:
    logger.info("[NIJA-PREFLIGHT] Preflight check passed ✅ Ready for live trading.")
