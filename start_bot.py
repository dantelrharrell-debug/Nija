#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
from loguru import logger

try:
    from nija_client import CoinbaseClient as NijaClient
except ImportError:
    try:
        from nija_client import NijaCoinbaseClient as NijaClient
    except ImportError:
        raise ImportError("Neither 'CoinbaseClient' nor 'NijaCoinbaseClient' could be imported from nija_client.py")

# -------------------------
# Initialize Nija Bot
# -------------------------
logger.info("Starting Nija bot (entrypoint)")

try:
    client = NijaClient()
except Exception as e:
    logger.error("Failed to initialize Nija client:", e)
    raise Exception("Failed to initialize Nija client") from e

# -------------------------
# Fetch and log balances
# -------------------------
def fetch_and_log_balances():
    try:
        balances = client.get_balances()
        if not balances:
            logger.warning("[NIJA-BALANCE] No balances returned (check JWT/PEM/ISS)")
            return
        for cur, amt in balances.items():
            logger.info(f"[NIJA-BALANCE] {cur}: {amt}")
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching balances: {e}")

# -------------------------
# Main Loop
# -------------------------
def main_loop():
    while True:
        fetch_and_log_balances()
        # -------------------------
        # TODO: Insert live trading logic here
        # Example: listen to TradingView alerts, execute trades
        # -------------------------
        time.sleep(5)  # polling interval; adjust as needed

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    try:
        fetch_and_log_balances()
        logger.info("Startup complete — bot ready for live trading")
        main_loop()
    except KeyboardInterrupt:
        logger.info("Nija bot stopped by user")
    except Exception as e:
        logger.error("Unhandled error in main loop:", e)
        raise
