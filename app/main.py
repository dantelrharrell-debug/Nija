# /app/main.py
import os
import logging
from nija_client import get_coinbase_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

# Instantiate Coinbase client (safe)
client = get_coinbase_client(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
    pem=COINBASE_PEM_CONTENT,
    org_id=COINBASE_ORG_ID
)


def main():
    # Fetch accounts safely
    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.warning(f"Failed to fetch accounts (dry-run or error): {e}")

    # Place example order safely
    try:
        order = client.place_order(
            product_id="BTC-USD",
            side="buy",
            price="50000",
            size="0.001"
        )
        logger.info(f"Order result: {order}")
    except Exception as e:
        logger.warning(f"Order not executed (dry-run or error): {e}")


if __name__ == "__main__":
    logger.info("Starting Nija bot...")
    main()
    logger.info("Bot finished execution.")
