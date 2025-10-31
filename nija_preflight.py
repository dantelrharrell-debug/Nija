import logging
from nija_coinbase_client import get_usd_balance
from nija_coinbase_jwt import get_jwt_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

def preflight_check():
    logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

    # Generate JWT
    try:
        token = get_jwt_token()
        logger.info("[NIJA-PREFLIGHT] JWT generated successfully.")
    except Exception as e:
        logger.error("[NIJA-PREFLIGHT] Failed to generate JWT: %s", e)
        return False

    # Fetch USD balance
    balance = get_usd_balance()
    if balance <= 0:
        logger.warning("[NIJA-PREFLIGHT] USD balance is zero or unavailable — check funding or permissions.")
        return False

    logger.info("[NIJA-PREFLIGHT] Preflight check passed. USD balance: $%s", balance)
    return True

if __name__ == "__main__":
    success = preflight_check()
    if success:
        logger.info("[NIJA-PREFLIGHT] All checks passed — ready to go live!")
    else:
        logger.warning("[NIJA-PREFLIGHT] Preflight failed — resolve errors before going live.")
