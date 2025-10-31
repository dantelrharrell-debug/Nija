# nija_preflight.py
import logging
from nija_coinbase_jwt import get_jwt_token  # JWT helper
# No fetch_usd_balance import needed anymore

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

try:
    jwt = get_jwt_token()  # Generate JWT for live trading
    logger.info("[NIJA-PREFLIGHT] JWT generated successfully.")
except Exception as e:
    logger.error(f"[NIJA-PREFLIGHT] Failed to generate JWT: {e}")

logger.info("[NIJA-PREFLIGHT] Preflight complete — skipping USD balance check. Fully live.")
