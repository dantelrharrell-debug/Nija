# nija_client.py
import logging

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# -------------------------
# Mock client for dry-run
# -------------------------
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"MockClient.place_order() called with args={args}, kwargs={kwargs}")
        return {"status": "simulated"}

# -------------------------
# Coinbase SDK import
# -------------------------
COINBASE_AVAILABLE = False
try:
    from coinbase.rest import RESTClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase SDK import succeeded via: from coinbase.rest import RESTClient")
except Exception as e:
    logger.warning(f"Coinbase SDK not available, will use MockClient: {e}")

# -------------------------
# Get Coinbase client
# -------------------------
def get_coinbase_client(api_key=None, api_secret=None, pem=None, org_id=None):
    """
    Returns a live Coinbase client if available, otherwise a mock client.
    Note: Standard RESTClient does NOT accept pem/org_id.
    """
    if COINBASE_AVAILABLE and api_key and api_secret:
        try:
            client = RESTClient(api_key=api_key, api_secret=api_secret)
            logger.info("✅ Live Coinbase client instantiated")
            return client
        except Exception as e:
            logger.error(f"❌ Failed to instantiate LiveClient: {e}")
            return MockClient()
    else:
        logger.warning("⚠️ Coinbase SDK not available or missing API keys — using MockClient")
        return MockClient()
