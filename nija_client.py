# nija_client.py
import os
import sys
import logging

# Optional: add local libs folder if package isn’t installed via pip
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "libs"))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Import CoinbaseClient ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError as e:
    logger.error("[NIJA] CoinbaseClient not available — cannot trade live")
    raise e  # Fail fast if library is missing

# --- Initialize live client ---
client = CoinbaseClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET"),
    passphrase=os.getenv("COINBASE_API_PASSPHRASE")  # optional
)

logger.info("[NIJA] Live RESTClient instantiated — ready to trade")
