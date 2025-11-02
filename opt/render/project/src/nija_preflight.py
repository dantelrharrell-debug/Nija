# -----------------------------
# nija_preflight.py (LIVE ONLY)
# -----------------------------
import logging
from nija_client import client, get_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

# -----------------------------
# Preflight
# -----------------------------
try:
    balance = get_usd_balance()
    logger.info(f"[NIJA] CoinbaseClient authenticated. USD Balance: {balance}")
    logger.info("[NIJA] Mode: LIVE")
except Exception as e:
    logger.error(f"[NIJA] Preflight failed: {e}")
    raise SystemExit("[NIJA] Cannot start bot. Fix credentials or connection before running.")
