import os
import time
import logging
from loguru import logger
from nija_client import COINBASE_AVAILABLE, AdvancedClient, MockClient

# Load environment variables
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 5))  # seconds

# Setup logging
logging.basicConfig(level=logging.INFO)

# --- Coinbase client ---
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


# Instantiate client
client = get_coinbase_client(pem=COINBASE_PEM_CONTENT, org_id=COINBASE_ORG_ID)

# --- Bot main logic ---
def main():
    logger.info("ℹ️ Starting Nija bot...")
    while True:
        try:
            # Fetch accounts
            try:
                accounts = client.get_accounts()
                logger.info(f"Accounts fetched: {accounts}")
            except Exception as e:
                logger.warning(f"Failed to fetch accounts (dry-run or error): {e}")
                accounts = []

            # Example trading logic
            for account in accounts:
                try:
                    # Replace this with real trading signals
                    order_result = client.place_order(
                        product_id="BTC-USD",
                        side="buy",
                        price="50000",
                        size="0.001"
                    )
                    logger.info(f"Order result: {order_result}")
                except Exception as e:
                    logger.warning(f"Order not executed (dry-run or error): {e}")

            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
