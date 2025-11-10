#!/usr/bin/env python3
# start_bot.py (root)
import time
from loguru import logger

# Try to import from app.nija_client first (if you later want app/ package), else fall back to root module.
try:
    from app.nija_client import CoinbaseClient  # will fail if app/ package not present
    logger.info("Imported CoinbaseClient from app.nija_client")
except Exception:
    try:
        from nija_client import CoinbaseClient
        logger.info("Imported CoinbaseClient from nija_client")
    except Exception as e:
        logger.exception("Failed to import CoinbaseClient from app.nija_client or nija_client: %s", e)
        raise

logger.info("Starting quick import/run test")
client = CoinbaseClient()
logger.info("Client created: %s", client)
# quick sanity
balances = client.get_balances()
logger.info("get_balances() returned: %s", balances)
print("IMPORT_TEST_OK")
