# nija_client.py
import os
import logging

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

USE_DUMMY = False
client = None

try:
    from coinbase_advanced_py.client import CoinbaseClient

    # Load environment keys
    COINBASE_KEY = os.getenv("COINBASE_API_KEY")
    COINBASE_SECRET = os.getenv("COINBASE_API_SECRET")
    COINBASE_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
    SANDBOX = os.getenv("COINBASE_SANDBOX", "false").lower() == "true"

    if not COINBASE_KEY or not COINBASE_SECRET or not COINBASE_PASSPHRASE:
        raise ValueError("Missing Coinbase API keys")

    client = CoinbaseClient(
        api_key=COINBASE_KEY,
        api_secret=COINBASE_SECRET,
        passphrase=COINBASE_PASSPHRASE,
        sandbox=SANDBOX
    )
    logger.info("[NIJA] Live RESTClient/CoinbaseClient instantiated (USE_DUMMY=False)")

except Exception as e:
    logger.error(f"[NIJA] Failed to import CoinbaseClient or missing keys: {e}")
    raise RuntimeError("Live trading cannot start without CoinbaseClient and valid API keys.")
