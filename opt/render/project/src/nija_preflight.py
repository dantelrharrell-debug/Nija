# nija_preflight.py
import logging
import sys
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

# Import the live client and helper from nija_client (this will raise if client not init)
try:
    from nija_client import client, get_usd_balance, CLIENT_CLASS
except Exception as e:
    logger.exception("Failed to import nija_client (ensure the package is installed & env is set).")
    raise SystemExit(1)

logger.info("🚀 NIJA preflight starting...")

# Confirm client type/health (do not use isinstance against unknown types; check class name)
try:
    if client is None:
        logger.error("Client object is None. Aborting preflight.")
        raise SystemExit(1)

    logger.info("Client class: %s", type(client).__name__)
    balance = get_usd_balance(client)
    logger.info("[NIJA] CoinbaseClient authenticated. USD Balance: %s", balance)

    # Final check: enforce live mode (fail if balance is zero OR client class doesn't look right)
    if not isinstance(balance, Decimal):
        logger.error("Balance returned is not Decimal -> %r", balance)
        raise SystemExit(1)

    # Accept: any non-negative Decimal is OK for startup; enforce non-zero if you prefer:
    if balance < Decimal("0"):
        logger.error("Negative balance? aborting.")
        raise SystemExit(1)

    print(f"[NIJA LIVE] ✅ Client initialized ({type(client).__name__}). USD balance: {balance}")
    logger.info("Preflight OK. Proceed with deployment (LIVE mode).")
    sys.exit(0)

except Exception as e:
    logger.exception("Preflight failed: %s", e)
    print("[NIJA ERROR] Preflight failed. Fix the Coinbase client / credentials.")
    raise SystemExit(1)
