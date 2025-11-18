import os
import logging

logger = logging.getLogger(__name__)

# --- Coinbase SDK import ---
COINBASE_AVAILABLE = False
AdvancedClient = None

try:
    from coinbase_advanced.client import Client as AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK available")
except ModuleNotFoundError:
    logger.warning("⚠️ Coinbase Advanced SDK not available, using MockClient")
    AdvancedClient = None

# --- Mock client for dry-run ---
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"MockClient.place_order() called with args={args}, kwargs={kwargs}")
        return {"status": "simulated"}


# --- Factory for client ---
def get_coinbase_client(pem=None, org_id=None):
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
