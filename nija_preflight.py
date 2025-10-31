# nija_preflight.py
import argparse
import logging
from nija_coinbase_client import fetch_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

# --- Add argument parsing ---
parser = argparse.ArgumentParser(description="Nija preflight check")
parser.add_argument(
    "--skip-balance-check",
    action="store_true",
    help="Skip checking USD balance to allow going live immediately"
)
args = parser.parse_args()

logger.info("[NIJA-PREFLIGHT] Starting preflight check... ✅")

# --- Skip balance check if requested ---
if args.skip_balance_check:
    logger.warning("[NIJA-PREFLIGHT] Skipping USD balance check as requested.")
else:
    try:
        usd_balance = fetch_usd_balance()
        logger.info(f"[NIJA-PREFLIGHT] USD balance fetched: ${usd_balance}")
        if usd_balance == 0:
            logger.warning("[NIJA-PREFLIGHT] USD balance is zero — check funding or permissions.")
    except Exception as e:
        logger.error(f"[NIJA-PREFLIGHT] Error fetching USD balance: {e}")
        logger.warning("[NIJA-PREFLIGHT] USD balance unavailable — check funding or permissions.")

# --- Continue with the rest of preflight/startup tasks ---
logger.info("[NIJA-PREFLIGHT] Preflight complete, moving on to startup...")
