#!/usr/bin/env python3
# nija_client.py
import os
import logging
from decimal import Decimal

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Coinbase Client ---
CoinbaseClient = None

try:
    from coinbase_advanced_py import CoinbaseClient
except ModuleNotFoundError as e:
    logger.error(f"[NIJA] Coinbase client import failed: {e}")
    raise

# --- Environment Variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise EnvironmentError("[NIJA] Missing Coinbase API credentials in environment variables!")

# --- Initialize live client ---
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
logger.info("[NIJA] CoinbaseClient initialized — LIVE trading ENABLED")
