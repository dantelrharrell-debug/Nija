try:
    from coinbase_advanced_py.client import AdvancedClient
    COINBASE_AVAILABLE = True
    print("✅ Coinbase Advanced SDK installed")
except ImportError:
    COINBASE_AVAILABLE = False
    print("⚠️ Coinbase Advanced SDK NOT installed, using MockClient")


import os
from loguru import logger

# --------------------------------
# Mock client (dry-run fallback)
# --------------------------------
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"MockClient.place_order() called with args={args}, kwargs={kwargs}")
        return {"status": "simulated"}

# --------------------------------
# Try to import Coinbase Advanced SDK
# --------------------------------
COINBASE_AVAILABLE = False
try:
    from coinbase_advanced_py.client import AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK import succeeded")
except ImportError:
    logger.warning("⚠️ Coinbase Advanced SDK not available, using MockClient")

# --------------------------------
# Load credentials from environment
# --------------------------------
PEM = os.environ.get("COINBASE_PEM_CONTENT")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

# --------------------------------
# Get Coinbase client
# --------------------------------
def get_coinbase_client(pem=None, org_id=None):
    """
    Returns a live AdvancedClient if SDK is available and PEM/org_id are provided,
    otherwise falls back to MockClient.
    """
    if COINBASE_AVAILABLE and pem and org_id:
        try:
            client = AdvancedClient(pem=pem, org_id=org_id)
            logger.info("✅ Live Coinbase Advanced client instantiated")
            return client
        except Exception as e:
            logger.error(f"❌ Failed to instantiate AdvancedClient: {e}")
            return MockClient()
    else:
        logger.warning("⚠️ Coinbase Advanced client unavailable, using MockClient")
        return MockClient()

# --------------------------------
# Instantiate client for main bot
# --------------------------------
client = get_coinbase_client(pem=PEM, org_id=ORG_ID)
