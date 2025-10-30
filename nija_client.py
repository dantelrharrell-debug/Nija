import os
import logging

logger = logging.getLogger("nija_client")
USE_DUMMY = True
client = None

try:
    # Attempt to import Coinbase client
    from coinbase_advanced_py.client import CoinbaseClient
    
    # Read environment variables
    COINBASE_KEY = os.getenv("COINBASE_API_KEY")
    COINBASE_SECRET = os.getenv("COINBASE_API_SECRET")
    COINBASE_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
    SANDBOX = os.getenv("COINBASE_SANDBOX", "true").lower() == "true"

    if COINBASE_KEY and COINBASE_SECRET and COINBASE_PASSPHRASE:
        client = CoinbaseClient(
            api_key=COINBASE_KEY,
            api_secret=COINBASE_SECRET,
            passphrase=COINBASE_PASSPHRASE,
            sandbox=SANDBOX
        )
        USE_DUMMY = False
        logger.info("[NIJA] Live CoinbaseClient ready for trading")
    else:
        raise ValueError("Missing API keys, using DummyClient")
except Exception as e:
    logger.warning(f"[NIJA] CoinbaseClient not available or keys missing: {e}")
    from .dummy_client import DummyClient
    client = DummyClient()
    USE_DUMMY = True
    logger.info("[NIJA] Using DummyClient (no live trades)")
