# main.py

import os
import time
import logging
from nija_client import get_coinbase_client, MockClient

# ---------------------------
# Logging setup
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------
# Load environment variables
# ---------------------------
COINBASE_PEM = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")

if not COINBASE_PEM or not COINBASE_ORG_ID:
    logger.warning("⚠️ PEM or ORG_ID not found in environment. Bot will use MockClient.")

# ---------------------------
# Initialize Coinbase client
# ---------------------------
client = get_coinbase_client(
    pem=COINBASE_PEM,
    org_id=COINBASE_ORG_ID
)

# ---------------------------
# Helper function: fetch accounts
# ---------------------------
def fetch_accounts():
    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
        return accounts
    except Exception as e:
        logger.warning(f"Failed to fetch accounts (dry-run or error): {e}")
        return []

# ---------------------------
# Helper function: place order
# ---------------------------
def place_order(product_id: str, side: str, price: str, size: str):
    try:
        result = client.place_order(
            product_id=product_id,
            side=side,
            price=price,
            size=size
        )
        logger.info(f"Order result: {result}")
        return result
    except Exception as e:
        logger.warning(f"Order not executed (dry-run or error): {e}")
        return {"status": "simulated"}

# ---------------------------
# Main bot loop
# ---------------------------
def main():
    logger.info("Starting Nija bot...")
    while True:
        accounts = fetch_accounts()
        
        if accounts:
            # Example: Buy 0.001 BTC at 50,000 USD (simulated)
            place_order(product_id="BTC-USD", side="buy", price="50000", size="0.001")
        
        # Sleep for 10 seconds before next loop (adjust as needed)
        time.sleep(10)

# ---------------------------
# Entry point
# ---------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
