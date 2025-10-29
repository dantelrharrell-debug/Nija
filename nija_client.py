import os
import logging
from coinbase_advanced_py.client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# ----- Live API keys (no terminal needed) -----
API_KEY = "your_live_api_key_here"
API_SECRET = "your_live_api_secret_here"
API_PASSPHRASE = "your_passphrase_here"  # optional, depends on account type

try:
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=API_PASSPHRASE
    )
    client_attached = True
    logger.info("[NIJA] Live Coinbase client attached successfully ✅")
except Exception as e:
    client = None
    client_attached = False
    logger.error(f"[NIJA] Failed to attach live client: {e}")
