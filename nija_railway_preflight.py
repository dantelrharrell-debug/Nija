# nija_railway_preflight.py
import logging
from nija_coinbase_jwt import get_jwt_token, debug_print_jwt_payload
from nija_coinbase_client import get_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

# --- Step 1: Check environment keys ---
try:
    jwt_token = get_jwt_token()
    logger.info("[NIJA-PREFLIGHT] JWT generated successfully.")
    debug_print_jwt_payload()
except Exception as e:
    logger.error("[NIJA-PREFLIGHT] Failed to generate JWT: %s", e)
    jwt_token = None

# --- Step 2: Check USD balance ---
try:
    usd_balance = get_usd_balance()
    if usd_balance is None or usd_balance == 0:
        logger.warning("[NIJA-PREFLIGHT] USD balance is zero or unavailable — check funding or permissions.")
    else:
        logger.info("[NIJA-PREFLIGHT] USD balance fetched successfully: %s", usd_balance)
except Exception as e:
    logger.error("[NIJA-PREFLIGHT] Failed to fetch USD balance: %s", e)

# --- Step 3: Final status ---
if jwt_token and usd_balance and usd_balance > 0:
    logger.info("[NIJA-PREFLIGHT] Preflight check complete ✅ Ready for live trading.")
else:
    logger.warning("[NIJA-PREFLIGHT] Preflight complete, but some checks failed. Resolve errors before going live.")
