#!/usr/bin/env python3
# start_bot.py (root)
import time
from loguru import logger

# Prefer app.nija_client if you later add an app package, but fall back to root nija_client
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

# Single fetch to verify
balances = client.get_balances()
if not balances:
    logger.warning("[NIJA-BALANCE] No balances returned (check service key scopes, COINBASE_BASE, COINBASE_ISS, and API credentials)")
else:
    for k, v in balances.items():
        logger.info(f"[NIJA-BALANCE] {k}: {v}")

# Main loop (replace with trading logic)
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
