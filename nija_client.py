# nija_client.py
import os
import time
import logging
from decimal import Decimal

# Correct import for v1.8.2
from coinbase_advanced_py import CoinbaseClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
SANDBOX = os.getenv("SANDBOX", "True").lower() == "true"

# Initialize Coinbase client
client = CoinbaseClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    passphrase=API_PASSPHRASE,
    sandbox=SANDBOX
)

logger.info(f"CoinbaseClient initialized. Sandbox={SANDBOX}")

# ===== Helper functions =====
def get_accounts():
    try:
        accounts = client.get_accounts()
        logger.info(f"Fetched {len(accounts)} accounts")
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return []

def place_order(symbol, side, size, order_type="market"):
    try:
        order = client.place_order(
            product_id=symbol,
            side=side,
            order_type=order_type,
            size=str(size)
        )
        logger.info(f"Order placed: {order}")
        return order
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return None
