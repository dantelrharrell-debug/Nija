import os
import logging
from coinbase_advanced_py.client import CoinbaseClient

# Get PEM key from environment
pem_string = os.getenv("API_PEM_B64")

if pem_string:
    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
        pem=pem_string
    )
    logging.info("✅ CoinbaseClient initialized successfully with PEM key.")
else:
    logging.warning("⚠️ CoinbaseClient not found. Falling back to stub client.")
    
    # If you don’t have a stub client defined yet:
    class StubCoinbaseClient:
        def get_accounts(self):
            return []
    
    client = StubCoinbaseClient()
