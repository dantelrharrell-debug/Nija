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
