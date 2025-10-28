# nija_client.py
import os
import logging
from decimal import Decimal
from coinbase_advanced_py.client import CoinbaseClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    logger.error("Coinbase API keys are missing! Please set environment variables.")
    raise EnvironmentError("Missing Coinbase API credentials")

# Initialize Coinbase client
client = CoinbaseClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    api_passphrase=API_PASSPHRASE,
    sandbox=False  # Set True if you want testnet
)

# Helper functions
def get_accounts():
    """Return Coinbase accounts as a dict."""
    try:
        accounts = client.get_accounts()
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return []

def place_order(account_id: str, side: str, product_id: str, size: str, price: str = None):
    """
    Place a Coinbase order.
    side: 'buy' or 'sell'
    size: quantity to buy/sell
    price: optional limit price
    """
    try:
        order = client.place_order(
            account_id=account_id,
            side=side,
            product_id=product_id,
            size=size,
            price=price,
        )
        logger.info(f"Order placed: {order}")
        return order
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return None
