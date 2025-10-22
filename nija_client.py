import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

from nija_client import client, CLIENT
from nija_orders import fetch_account_balance

if client:
    print("Client attached:", client)
    balance = fetch_account_balance(client)
    print("Live account balance:", balance)
else:
    print("Simulation mode active, cannot fetch balance.")

# Optional: direct CoinbaseClient test
try:
    from coinbase_advanced_py.client import CoinbaseClient
    print("✅ CoinbaseClient imported successfully")
except Exception as e:
    print(f"⚠️ Import failed: {e}")

# ----- nija_client.py -----
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

import logging

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("nija.client")

CLIENT = None
client = None

# Try to import coinbase_advanced_py
try:
    from coinbase_advanced_py.client import CoinbaseClient as CoinbaseAdvancedClient
except Exception:
    CoinbaseAdvancedClient = None
    _logger.warning("coinbase_advanced_py not installed or failed to import.")

def attach_coinbase_client_from_env():
    api_key = os.getenv("COINBASE_KEY") or os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_SECRET") or os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_PASSPHRASE")  # optional

    if not api_key or not api_secret:
        _logger.info(f"Coinbase keys not found. KEY={api_key}, SECRET={api_secret}")
        _logger.info("Running in simulation mode (no live trades).")
        return None

    if CoinbaseAdvancedClient is not None:
        try:
            _logger.info("Instantiating coinbase_advanced_py CoinbaseClient from env vars.")
            c = CoinbaseAdvancedClient(api_key=api_key, api_secret=api_secret)
            _logger.info("Coinbase client instantiated successfully.")
            return c
        except Exception as e:
            _logger.exception("Failed to instantiate CoinbaseAdvancedClient: %s", e)

    _logger.warning("No compatible Coinbase client library available or instantiation failed. Running in simulation mode.")
    return None

client = attach_coinbase_client_from_env()
CLIENT = client
# ----- end nija_client.py -----
