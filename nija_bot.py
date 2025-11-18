import os
import time
import logging
from loguru import logger

# ----------------------
# Environment Variables
# ----------------------
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
TRADE_INTERVAL = int(os.getenv("TRADE_INTERVAL", 60))  # seconds

# ----------------------
# Coinbase Client Setup
# ----------------------
COINBASE_AVAILABLE = False
AdvancedClient = None

# Try to import Coinbase Advanced SDK
try:
    from coinbase_advanced.client import Client as AdvancedClient
    COINBASE_AVAILABLE = True
    logger.info("✅ Coinbase Advanced SDK available")
except ModuleNotFoundError:
    logger.warning("⚠️ Coinbase Advanced SDK not available, will use MockClient")
except Exception as e:
    logger.error(f"❌ Coinbase SDK import failed: {e}")

# ----------------------
# Mock Client (dry-run)
# ----------------------
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, **kwargs):
        logger.info(f"MockClient.place_order() called with {kwargs}")
        return {"status": "simulated"}

# ----------------------
# Coinbase Client Getter
# ----------------------
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

# ----------------------
# Main Bot Logic
# ----------------------
def run_bot(client):
    while True:
        try:
            # 1️⃣ Fetch accounts
            accounts = client.get_accounts()
            logger.info(f"Accounts fetched: {accounts}")

            # 2️⃣ Example trading logic
            # Replace with your own strategy
            for account in accounts:
                if account["currency"] == "USD" and float(account["balance"]) > 10:
                    result = client.place_order(
                        product_id="BTC-USD",
                        side="buy",
                        price="50000",  # example
                        size="0.001"
                    )
                    logger.info(f"Order result: {result}")

        except Exception as e:
            logger.error(f"⚠️ Bot runtime error: {e}")

        # Wait until next trade cycle
        time.sleep(TRADE_INTERVAL)

# ----------------------
# Entry Point
# ----------------------
if __name__ == "__main__":
    logger.info("ℹ️ Starting Nija bot...")
    client = get_coinbase_client(pem=COINBASE_PEM_CONTENT, org_id=COINBASE_ORG_ID)
    run_bot(client)
