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

try:
    # Try Coinbase SDK first
    from coinbase_advanced_py.client import CoinbaseClient
    client = CoinbaseClient(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE", None)
    )
    logger.info("[NIJA] Live CoinbaseClient instantiated")
except ModuleNotFoundError:
    # Fallback to REST-only client if SDK missing
    try:
        from coinbase_rest_client import RESTClient
        client = RESTClient(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET")
        )
        logger.info("[NIJA] Live RESTClient instantiated (no passphrase required)")
    except Exception as e:
        logger.warning(f"[NIJA] Could not create live client: {e}")
        USE_DUMMY = True
        from dummy_client import DummyClient
        client = DummyClient()
        logger.info("[NIJA] DummyClient instantiated — live trading disabled")
