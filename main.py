import os
import time
from loguru import logger

# --------------------------------
# Load environment variables
# --------------------------------
PEM = os.environ.get("COINBASE_PEM_CONTENT")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

# --------------------------------
# Coinbase Advanced SDK availability
# --------------------------------
COINBASE_AVAILABLE = False
try:
    from coinbase_advanced_py.client import AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK import succeeded")
except ImportError:
    COINBASE_AVAILABLE = False
    logger.warning("⚠️ Coinbase Advanced SDK not installed, using MockClient")

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
# Trading bot logic
# --------------------------------
def main():
    logger.info("🚀 Starting Nija bot...")

    # Instantiate Coinbase client (live or mock)
    client = get_coinbase_client(PEM, ORG_ID)

    # Fetch accounts
    accounts = client.get_accounts()
    logger.info(f"Accounts fetched: {accounts}")

    # Example order: Buy 0.001 BTC at $50,000
    try:
        order = client.place_order(
            product_id="BTC-USD",
            side="buy",
            price="50000",
            size="0.001"
        )
        logger.info(f"Order result: {order}")
    except Exception as e:
        logger.error(f"❌ Failed to place order: {e}")

    # Keep running 24/7
    while True:
        time.sleep(60)  # Check every minute
        # Add your trading logic here (signal checks, alerts, etc.)
        # Example: log current accounts each minute
        try:
            accounts = client.get_accounts()
            logger.info(f"Accounts snapshot: {accounts}")
        except Exception as e:
            logger.error(f"❌ Error fetching accounts: {e}")

# --------------------------------
# Entry point
# --------------------------------
if __name__ == "__main__":
    main()
