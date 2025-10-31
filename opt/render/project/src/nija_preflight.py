import logging
from nija_coinbase_client import get_usd_balance
from nija_coinbase_jwt import debug_print_jwt_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

# Step 1: JWT sanity check
try:
    debug_print_jwt_payload()
    logger.info("[NIJA-PREFLIGHT] JWT generated successfully.")
except Exception as e:
    logger.error("[NIJA-PREFLIGHT] JWT generation failed: %s", e)

# Step 2: USD balance
balance = get_usd_balance()
if balance is None or balance == 0:
    logger.warning("[NIJA-PREFLIGHT] USD balance is zero or unavailable — check funding or permissions.")
else:
    logger.info("[NIJA-PREFLIGHT] Preflight check passed. USD balance: $%s", balance)
