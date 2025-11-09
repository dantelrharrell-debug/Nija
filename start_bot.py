#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
from loguru import logger
from nija_client import CoinbaseClient as NijaClient

# -------------------------
# Initialize Nija Bot
# -------------------------
logger.info("Starting Nija bot (entrypoint)")

try:
    client = NijaClient()
except Exception as e:
    logger.error("Failed to initialize Nija client:", e)
    raise

# -------------------------
# Fetch and print balances
# -------------------------
def fetch_and_log_balances():
    balances = client.get_balances()
    if not balances:
        logger.warning("[NIJA-BALANCE] No balances returned (check JWT/PEM/ISS)")
        return
    usd_balance = balances.get("USD", 0) if isinstance(balances, dict) else 0
    logger.success(f"[NIJA-BALANCE] USD: {usd_balance}")
    for cur, amt in balances.items():
        if cur != "USD":
            logger.info(f"[NIJA-BALANCE] {cur}: {amt}")

# -------------------------
# Main Loop
# -------------------------
def main_loop():
    while True:
        fetch_and_log_balances()
        time.sleep(5)  # adjust polling interval as needed

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
        raise Exception as e:
    logger.error("Failed to initialize Nija client:", e)
    raise

# -------------------------
# Fetch and print balances
# -------------------------
def fetch_and_log_balances():
    balances = client.get_balances()
    if not balances:
        logger.warning("[NIJA-BALANCE] No balances returned (check JWT/PEM/ISS)")
        return
    for cur, amt in balances.items():
        logger.info(f"[NIJA-BALANCE] {cur}: {amt}")

# -------------------------
# Main Loop
# -------------------------
def main_loop():
    while True:
        fetch_and_log_balances()
        time.sleep(5)  # adjust polling interval as needed

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

# start_bot.py
import os
import time
from loguru import logger

try:
    from nija_client import CoinbaseClient as _Client
except ImportError:
    try:
        from nija_client import NijaCoinbaseClient as _Client
    except ImportError:
        raise ImportError("Neither 'CoinbaseClient' nor 'NijaCoinbaseClient' could be imported from nija_client.py")

# --- Initialize client ---
client = _Client()

logger.info("Starting Nija bot (entrypoint)")

# --- Fetch USD balance safely ---
try:
    if hasattr(client, "get_balances"):
        balances = client.get_balances()
    elif hasattr(client, "get_accounts"):
        balances = client.get_accounts()
    else:
        balances = {}
    usd_balance = balances.get("USD", 0) if isinstance(balances, dict) else 0
    logger.success(f"USD balance fetched: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
    usd_balance = 0

# --- Startup complete message ---
logger.info("Startup complete — bot ready for live trading")

# --- Example live loop (replace with your trading logic) ---
try:
    while True:
        # Fetch balances each tick
        try:
            balances = client.get_balances()
            usd_balance = balances.get("USD", 0) if isinstance(balances, dict) else 0
            logger.info(f"[NIJA-BALANCE] USD: {usd_balance}")
        except Exception as e:
            logger.warning(f"Balance fetch failed: {e}")
        
        # --- TODO: insert live trading signal handling here ---
        # e.g., listen for TradingView alerts, execute trade

        time.sleep(5)  # tick interval; adjust as needed
except KeyboardInterrupt:
    logger.info("Bot stopped manually")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
finally:
    logger.info("Exiting Nija bot")
