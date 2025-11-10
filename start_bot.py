#!/usr/bin/env python3
# start_bot.py (root)
import time
from loguru import logger

# Try to import from app.nija_client if available, otherwise fall back to nija_client at project root
try:
    from app.nija_client import CoinbaseClient
except Exception:
    try:
        from nija_client import CoinbaseClient
    except Exception as e:
        logger.exception("Failed to import CoinbaseClient from app.nija_client or nija_client: %s", e)
        raise

logger.add(lambda r: print(r, end=""))
logger.info("Starting Nija bot — LIVE mode")

client = CoinbaseClient()

# quick one-off fetch for immediate debug
balances = client.get_balances()
if not balances:
    logger.warning("[NIJA-BALANCE] No balances returned (check service key scopes, COINBASE_BASE, COINBASE_ISS)")
else:
    for k, v in balances.items():
        logger.info(f"[NIJA-BALANCE] {k}: {v}")

# main loop
try:
    while True:
        balances = client.get_balances()
        if not balances:
            logger.info("[NIJA-BALANCE] no balances returned this tick")
        else:
            usd = balances.get("USD", 0)
            if usd:
                logger.info(f"[NIJA-BALANCE] USD: {usd}")
            else:
                for cur, amt in balances.items():
                    logger.info(f"[NIJA-BALANCE] {cur}: {amt}")
        time.sleep(5)
except KeyboardInterrupt:
    logger.info("Nija bot stopped by user")
except Exception as e:
    logger.exception("Unhandled error in main loop: %s", e)
