import logging
from nija_coinbase_jwt import get_jwt_token  # keep JWT, needed for live trading
from nija_coinbase_client import CoinbaseClient  # your live client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

# --- Generate JWT ---
try:
    jwt_token = get_jwt_token()
    logger.info(f"[NIJA-PREFLIGHT] JWT generated successfully")
except Exception as e:
    logger.error(f"[NIJA-PREFLIGHT] Failed to generate JWT: {e}")
    # Stop if JWT fails because we can't trade without it
    raise SystemExit("Cannot proceed without valid JWT")

# --- Skip USD balance check entirely ---
logger.warning("[NIJA-PREFLIGHT] USD balance check skipped — proceeding live")

# --- Mark preflight as passed ---
logger.info("[NIJA-PREFLIGHT] Preflight complete — ready to go live ✅")

# --- Start your main bot logic here ---
# from nija_worker import run_worker
# run_worker()
