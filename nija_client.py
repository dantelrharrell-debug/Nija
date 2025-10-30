from coinbase_advanced_py import CoinbaseClient

#!/usr/bin/env python3
# nija_client.py
import os
import logging
from coinbase_advanced_py.client import CoinbaseClient

# ---------------------
# Logging
# ---------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# ---------------------
# Coinbase Client (LIVE ONLY)
# ---------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    raise RuntimeError("[NIJA] Coinbase API key/secret not set! Live trading cannot start.")

client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
logger.info("[NIJA] CoinbaseClient initialized - LIVE trading enabled")
