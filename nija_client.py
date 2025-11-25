import os
import logging
from coinbase_advanced import Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Load Coinbase credentials from environment variables
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")  # usually same as API key ID
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # optional

LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"

def get_coinbase_client():
    if not LIVE_TRADING:
        logging.warning("LIVE_TRADING disabled. Coinbase client will not be initialized.")
        return None

    # Verify required credentials
    missing = []
    if not COINBASE_API_KEY:
        missing.append("COINBASE_API_KEY")
    if not COINBASE_API_SECRET:
        missing.append("COINBASE_API_SECRET")
    if not COINBASE_API_SUB:
        missing.append("COINBASE_API_SUB")
    if not (COINBASE_PEM_PATH or COINBASE_PEM_CONTENT):
        missing.append("COINBASE_PEM_PATH or COINBASE_PEM_CONTENT")

    if missing:
        logging.error(f"Cannot initialize Coinbase client. Missing keys: {missing}")
        return None

    # Decide PEM source
    pem = None
    if COINBASE_PEM_CONTENT:
        pem = COINBASE_PEM_CONTENT
    elif COINBASE_PEM_PATH and os.path.isfile(COINBASE_PEM_PATH):
        with open(COINBASE_PEM_PATH, "r") as f:
            pem = f.read()
    else:
        logging.error("PEM file not found or PEM content empty.")
        return None

    # Initialize client
    try:
        client = Client(
            key=COINBASE_API_KEY,
            secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_SUB,
            pem=pem
        )
        logging.info("✅ Coinbase client initialized successfully.")
        return client
    except Exception as e:
        logging.exception(f"Failed to initialize Coinbase client: {e}")
        return None

# Example usage
coinbase_client = get_coinbase_client()

def test_coinbase_connection():
    if not coinbase_client:
        logging.warning("Coinbase client not initialized; cannot test connection.")
        return
    try:
        info = coinbase_client.get_accounts()
        logging.info(f"Connected to Coinbase. Accounts retrieved: {len(info)}")
    except Exception as e:
        logging.error(f"Coinbase connection test failed: {e}")

if __name__ == "__main__":
    test_coinbase_connection()
