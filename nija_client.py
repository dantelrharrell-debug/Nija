# nija_client.py
import os
import logging
from loguru import logger

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
# Coinbase Advanced SDK import
# -------------------------
COINBASE_AVAILABLE = False
try:
    from coinbase_advanced_py.client import Client as AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK imported successfully")
except Exception as e:
    logger.warning(f"Coinbase Advanced SDK not available, using MockClient: {e}")

# -------------------------
# Instantiate client
# -------------------------
def get_coinbase_client(pem=None, org_id=None):
    """
    Returns AdvancedClient if available, otherwise MockClient.
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
