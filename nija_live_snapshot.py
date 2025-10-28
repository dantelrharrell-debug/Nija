import os
import logging

# Try to import the real client
try:
    from coinbase_advanced_py.client import CoinbaseClient
except ImportError:
    logging.warning("coinbase_advanced_py.client not found. Using stub client.")
    CoinbaseClient = None

# Fallback stub client (you should have this already)
from nija_client import StubCoinbaseClient

# Read environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
PEM_STRING = os.getenv("API_PEM_B64")

# Initialize client
if CoinbaseClient and PEM_STRING:
    logging.info("✅ Initializing real CoinbaseClient with PEM key")
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=PASSPHRASE,
        pem=PEM_STRING
    )
else:
    logging.warning("⚠️ Using stub Coinbase client. Real trading disabled.")
    client = StubCoinbaseClient()
