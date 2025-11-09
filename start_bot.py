#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from loguru import logger
from nija_client import CoinbaseClient as NijaClient

logger.info("Starting Nija bot (entrypoint)")

# Initialize client
client = NijaClient()

def fetch_and_log_balances():
    balances = client.get_balances()
    if not balances:
        logger.warning("[NIJA-BALANCE] No balances returned (check JWT/PEM/ISS)")
        return
    for cur, amt in balances.items():
        logger.info(f"[NIJA-BALANCE] {cur}: {amt}")

# Run loop
try:
    fetch_and_log_balances()
    logger.info("Startup complete — bot ready for live trading")
    while True:
        fetch_and_log_balances()
        time.sleep(5)  # polling interval
except KeyboardInterrupt:
    logger.info("Nija bot stopped manually")
except Exception as e:
    logger.error("Unexpected error:", e)
finally:
    logger.info("Exiting Nija bot")
