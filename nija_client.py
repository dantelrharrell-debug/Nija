# nija_client.py
import os
import logging

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)

# Try importing CoinbaseClient
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] coinbase_advanced_py.client imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available")
    CoinbaseClient = None

def init_client():
    """
    Initialize Coinbase RESTClient using environment variables.
    PEM content is passed directly from ENV; no file writing needed.
    """
    if CoinbaseClient is None:
        logger.warning("[NIJA] CoinbaseClient unavailable, returning None")
        return None

    pem_content = os.getenv("COINBASE_PEM_CONTENT")
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")

    if not all([pem_content, api_key, api_secret, api_passphrase]):
        logger.error("[NIJA] Missing Coinbase API credentials in environment")
        return None

    try:
        client = CoinbaseClient(
            key=api_key,
            secret=api_secret,
            passphrase=api_passphrase,
            pem_content=pem_content  # pass PEM as string
        )
        logger.info("[NIJA] Coinbase RESTClient initialized successfully")
        return client
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize Coinbase client: {e}")
        return None
