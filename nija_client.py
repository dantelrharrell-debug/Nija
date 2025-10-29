import os, shutil, logging

# --- Setup logging ---
logger = logging.getLogger("nija_client")

# --- Clean up duplicate Coinbase folders ---
for name in ("coinbase_advanced_py", "coinbase-advanced-py"):
    folder = os.path.join(os.getcwd(), name)
    if os.path.isdir(folder):
        backup = os.path.join(os.getcwd(), "local_shadow_backups", name)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.move(folder, backup)
        logger.warning(f"[NIJA] Moved local shadow folder {folder} -> {backup}")

# --- Now safe to import CoinbaseClient ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient (live mode ready)")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not found, using DummyClient fallback")
    CoinbaseClient = None

import os
import logging
from decimal import Decimal

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Global client ---
client = None

# --- Try to initialize Coinbase client ---
try:
    from coinbase_advanced_py.client import CoinbaseClient

    # Fetch keys from environment variables
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

    if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
        raise ValueError("Coinbase API keys missing. Set COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE.")

    # Initialize live client
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
    logger.info("[NIJA] CoinbaseClient initialized -> Live trading ENABLED.")

except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not installed. Using simulated client.")
except Exception as e:
    logger.warning(f"[NIJA] CoinbaseClient initialization failed: {e}. Using simulated client.")

# --- Simulated fallback client ---
class DummyClient:
    def place_order(self, symbol, type, side, amount):
        logger.info(f"[DUMMY] Simulated order -> {side} {amount} {symbol}")
        return {
            "symbol": symbol,
            "type": type,
            "side": side,
            "amount": amount,
            "status": "simulated"
        }

# Attach dummy client if live client failed
if client is None:
    client = DummyClient()
    logger.info("[NIJA] DummyClient attached -> Simulated trading active.")
