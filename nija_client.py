import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Attempt to import CoinbaseClient
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    CoinbaseClient = None
    logger.warning("[NIJA] CoinbaseClient not available, running in simulation mode")

# Initialize client if API keys are available
client = None
if CoinbaseClient:
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
    
    if API_KEY and API_SECRET and API_PASSPHRASE:
        try:
            client = CoinbaseClient(API_KEY, API_SECRET, API_PASSPHRASE)
            logger.info("[NIJA] ✅ Live Coinbase client initialized — ready to trade!")
        except Exception as e:
            logger.error(f"[NIJA] Failed to initialize Coinbase client: {e}")
            client = None
    else:
        logger.warning("[NIJA] Coinbase API keys missing — running in simulation mode")
