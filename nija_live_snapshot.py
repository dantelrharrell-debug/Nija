import os
import logging

# Try to import real Coinbase client
try:
    from coinbase_advanced_py.client import CoinbaseClient
except ImportError:
    CoinbaseClient = None
    logging.warning("coinbase_advanced_py.client not found. Real trading disabled.")

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
PEM_STRING = os.getenv("API_PEM_B64")

# Initialize Coinbase client
client = None
if CoinbaseClient and PEM_STRING:
    logging.info("✅ Initializing real CoinbaseClient with PEM key")
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=PASSPHRASE,
        pem=PEM_STRING
    )
else:
    logging.warning("⚠️ Real CoinbaseClient not available. Trading disabled.")

# Start bot logic
logging.info("🌟 Nija bot is running...")
# ... trading loop or worker code here ...
