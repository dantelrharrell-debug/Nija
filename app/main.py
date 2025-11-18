# /app/main.py
import os
import logging
from nija_client import get_coinbase_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------
# 1) Load environment variables
# -------------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

# -------------------------
# 2) Instantiate Coinbase client (safe)
# -------------------------
client = get_coinbase_client(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
    pem=COINBASE_PEM_CONTENT,
    org_id=COINBASE_ORG_ID
)

# -------------------------
# 3) Example bot logic
# -------------------------
def main():
    if client is None:
        logger.warning("⚠️ Dry-run mode: Coinbase SDK unavailable, skipping live trading.")
    else:
        try:
            accounts = client.get_accounts()
            logger.info(f"Fetched accounts: {accounts}")
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
    
    # Example: placing an order safely
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


# -------------------------
# 4) Run
# -------------------------
if __name__ == "__main__":
    logger.info("Starting Nija bot...")
    main()
    logger.info("Bot finished execution.")
