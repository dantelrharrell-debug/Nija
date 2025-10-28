import os
import logging

# ------------------------------
# Coinbase imports
# ------------------------------
try:
    # Make sure this matches your installed package
    from coinbase_advanced_py.client import CoinbaseClient, CoinbaseError
except ImportError as e:
    CoinbaseClient = None
    CoinbaseError = None
    logging.warning(f"CoinbaseClient not found: {e}. Will use stub client if needed.")

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

def init_coinbase_client():
    global client
    if not CoinbaseClient:
        logging.warning("❌ CoinbaseClient not available.")
        return False

    if not API_KEY or not API_SECRET:
        logging.warning("❌ Coinbase API_KEY or API_SECRET missing.")
        return False

    if PEM_FILE:
        try:
            client = CoinbaseClient(API_KEY, API_SECRET, API_PASSPHRASE, pem_file=PEM_FILE)
            logging.info("✅ Coinbase client initialized with PEM file.")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to initialize with PEM file: {e}")
            return False

    elif PEM_STRING:
        try:
            client = CoinbaseClient(API_KEY, API_SECRET, API_PASSPHRASE, pem_string=PEM_STRING)
            logging.info("✅ Coinbase client initialized with PEM string.")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to initialize with PEM string: {e}")
            return False

    else:
        logging.warning("⚠️ No PEM file or string provided for Coinbase. Cannot initialize real client.")
        return False

# Attempt to initialize
if not init_coinbase_client():
    # ------------------------------
    # Fallback stub client
    # ------------------------------
    class StubClient:
        def get_accounts(self):
            return [
                {"id": "stub_usd", "currency": "USD", "balance": {"amount": "1000.0", "currency": "USD"}},
                {"id": "stub_btc", "currency": "BTC", "balance": {"amount": "0.0", "currency": "BTC"}},
            ]

        # Add other stub methods as needed

    client = StubClient()
    logging.warning("⚠️ Using stub Coinbase client. Real trading requires PEM string/file.")

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
        balance = account.get("balance", {})
        amount = balance.get("amount", "0.0")
        logging.info(f" - {account.get('currency', 'N/A')}: {amount}")
