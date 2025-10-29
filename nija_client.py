# nija_client.py
import logging
import time
from decimal import Decimal

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Live API keys (replace these with your actual keys) ---
API_KEY = "your_live_api_key_here"
API_SECRET = "your_live_api_secret_here"
API_PASSPHRASE = "your_passphrase_here"  # optional

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
client = None
client_attached = False

try:
    from coinbase_advanced_py.client import CoinbaseClient

    try:
        client = CoinbaseClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            passphrase=API_PASSPHRASE
        )
        client_attached = True
        logger.info("[NIJA] Live Coinbase client attached successfully ✅")
    except Exception as e:
        client = None
        client_attached = False
        logger.error(f"[NIJA] Failed to attach live client: {e}")

except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not found. Using DummyClient.")
    client_attached = False

# --- Dummy client for simulation if live client fails ---
class DummyClient:
    def place_order(self, *args, **kwargs):
        logger.info(f"[SIMULATED ORDER] args={args}, kwargs={kwargs}")
        return {"id": "SIM123", "status": "simulated"}

    def get_balance(self, *args, **kwargs):
        return {"USD": "1000.00"}

if not client_attached:
    client = DummyClient()
    logger.info("[NIJA] Running in SIMULATION mode ⚠️")

# --- Helper functions for trading ---
def place_order(side, product, size, price=None):
    """
    side: 'buy' or 'sell'
    product: e.g., 'BTC-USD'
    size: float, amount to trade
    price: float or None (market order if None)
    """
    try:
        if client_attached:
            order = client.place_order(
                side=side,
                product=product,
                size=str(size),
                price=str(price) if price else None,
            )
            logger.info(f"[NIJA] Live order executed: {order}")
            return order
        else:
            order = client.place_order(side=side, product=product, size=size, price=price)
            return order
    except Exception as e:
        logger.error(f"[NIJA] Error placing order: {e}")
        return None

def get_balance(currency="USD"):
    try:
        if client_attached:
            balance = client.get_balance(currency)
            logger.info(f"[NIJA] Live balance: {balance}")
            return balance
        else:
            balance = client.get_balance(currency)
            logger.info(f"[SIMULATION] Balance: {balance}")
            return balance
    except Exception as e:
        logger.error(f"[NIJA] Error getting balance: {e}")
        return None

# --- Example usage ---
if __name__ == "__main__":
    logger.info("=== NIJA Client Initialized ===")
    get_balance()
    # Example: place a small test order
    # place_order("buy", "BTC-USD", 0.001)
