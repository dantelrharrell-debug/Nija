import os
import logging

# ------------------------------
# Coinbase imports
# ------------------------------
try:
    from coinbase_advanced_py.client import CoinbaseClient, CoinbaseError
except ImportError:
    CoinbaseClient = None
    CoinbaseError = None
    logging.warning("CoinbaseClient not found. Falling back to stub client.")

# ------------------------------
# Coinbase credentials
# ------------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")
PEM_FILE = os.getenv("COINBASE_API_PEM_FILE")
PEM_STRING = os.getenv("COINBASE_API_PEM_STRING")

# ------------------------------
# Initialize Coinbase client
# ------------------------------
client = None

if CoinbaseClient and API_KEY and API_SECRET and (PEM_FILE or PEM_STRING):
    try:
        if PEM_FILE:
            client = CoinbaseClient(API_KEY, API_SECRET, API_PASSPHRASE, pem_file=PEM_FILE)
        else:
            client = CoinbaseClient(API_KEY, API_SECRET, API_PASSPHRASE, pem_string=PEM_STRING)
        logging.info("✅ Real Coinbase client initialized.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize Coinbase client: {e}")

# ------------------------------
# Stub client for testing/fallback
# ------------------------------
if client is None:
    class StubClient:
        def get_accounts(self):
            # Matches Coinbase API structure to prevent crash
            return [
                {"id": "stub_usd", "currency": "USD", "balance": {"amount": "1000.0", "currency": "USD"}},
                {"id": "stub_btc", "currency": "BTC", "balance": {"amount": "0.0", "currency": "BTC"}},
            ]
    client = StubClient()
    logging.warning("⚠️ Using stub Coinbase client. Set PEM string/file for real trading.")

# ------------------------------
# Helper functions
# ------------------------------
def get_accounts():
    try:
        return client.get_accounts()
    except Exception as e:
        logging.error(f"❌ Failed to fetch accounts: {e}")
        return []

def start_trading():
    logging.info("🔥 Trading loop starting...")
    accounts = get_accounts()
    for account in accounts:
        logging.info(f" - {account['currency']}: {account['balance']['amount']}")
