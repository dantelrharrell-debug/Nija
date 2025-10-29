# nija_client.py
import os
import time
import logging
from decimal import Decimal
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
    """
    Returns a list of all Coinbase accounts with balances.
    """
    try:
        accounts = client.get_accounts()
        logger.info(f"Fetched {len(accounts)} accounts")
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return []


def place_order(symbol, side, size, order_type="market"):
    """
    Place a trade order.
    :param symbol: str, e.g., 'BTC-USD'
    :param side: 'buy' or 'sell'
    :param size: float or str amount
    :param order_type: 'market' or 'limit'
    :return: dict response from Coinbase
    """
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
