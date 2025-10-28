# nija_client.py
import os
import time
import logging

# --- Coinbase import fix ---
try:
    from coinbase_advanced_py.client import CoinbaseClient, CoinbaseError
except ImportError:
    CoinbaseClient = None
    CoinbaseError = None
    logging.warning("CoinbaseClient not found. Falling back to stub client.")

# --- Environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")
COINBASE_API_PEM_FILE = os.getenv("COINBASE_API_PEM_FILE")
COINBASE_API_PEM_STRING = os.getenv("COINBASE_API_PEM_STRING")

# --- Initialize client ---
client = None
if CoinbaseClient and COINBASE_API_KEY and COINBASE_API_SECRET:
    try:
        if COINBASE_API_PEM_STRING:
            client = CoinbaseClient(
                api_key=COINBASE_API_KEY,
                api_secret=COINBASE_API_SECRET,
                pem_string=COINBASE_API_PEM_STRING
            )
        elif COINBASE_API_PEM_FILE:
            client = CoinbaseClient(
                api_key=COINBASE_API_KEY,
                api_secret=COINBASE_API_SECRET,
                pem_file=COINBASE_API_PEM_FILE
            )
        else:
            logging.warning("No PEM key provided. Using stub client.")
            client = None

        if client:
            accounts = client.get_accounts()
            logging.info(f"✅ Real Coinbase client initialized. Accounts: {accounts}")
    except CoinbaseError as e:
        logging.error(f"Coinbase client error: {e}")
        client = None
else:
    logging.warning("CoinbaseClient not initialized. Using stub client.")

# --- Stub client (if Coinbase fails) ---
class StubClient:
    def get_accounts(self):
        return {"USD": 1000.0, "BTC": 0.0}

if client is None:
    client = StubClient()
    logging.warning("⚠️ Using stub Coinbase client. Set PEM string/file for real trading.")

# --- Trading loop helpers ---
def start_trading():
    logging.info("🔥 Trading loop starting...")
    # Your trading loop logic here
    # Example:
    while True:
        try:
            accounts = client.get_accounts()
            logging.info(f"Accounts: {accounts}")
            time.sleep(10)
        except Exception as e:
            logging.error(f"Trading loop error: {e}")
            time.sleep(5)

def get_accounts():
    try:
        return client.get_accounts()
    except Exception as e:
        logging.error(f"Failed to fetch accounts: {e}")
        return {}
