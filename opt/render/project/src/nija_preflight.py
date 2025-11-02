# nija_preflight.py
import logging
from nija_client import client, get_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

logger.info("🚀 Starting NIJA Preflight Check...")

try:
    balance = get_usd_balance(client)
    logger.info(f"✅ Coinbase API connected. USD Balance: ${balance}")
    print(f"[NIJA LIVE] ✅ Connection OK - USD Balance: ${balance}")
except Exception as e:
    logger.error(f"❌ Preflight failed: {e}")
    print(f"[NIJA ERROR] {e}")
