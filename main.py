import os
import time
import logging
from nija_client import get_coinbase_client, MockClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_bot")

# Load environment variables
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

# Initialize Coinbase client
client = get_coinbase_client(
    pem=COINBASE_PEM_CONTENT,
    org_id=COINBASE_ORG_ID
)

def main():
    logger.info("🚀 Starting Nija bot...")
    while True:
        try:
            accounts = client.get_accounts()
            logger.info(f"Accounts fetched: {accounts}")

            # Example trade: buy 0.001 BTC at $50,000
            order_result = client.place_order(
                product_id="BTC-USD",
                side="buy",
                price="50000",
                size="0.001"
            )
            logger.info(f"Order result: {order_result}")

        except Exception as e:
            logger.error(f"❌ Error in bot loop: {e}")

        # Sleep 60s between iterations
        time.sleep(60)


if __name__ == "__main__":
    main()
