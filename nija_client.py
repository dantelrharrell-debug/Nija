import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Global variable for the Coinbase client
coinbase_client = None

# Detect if live trading is enabled
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"

def get_coinbase_client():
    global coinbase_client
    if coinbase_client:
        return coinbase_client

    if not LIVE_TRADING:
        logging.warning("LIVE_TRADING disabled. Coinbase client will not be initialized.")
        return None

    # Load environment variables
    COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
    COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
    COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
    COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # PEM as string

    missing = []
    if not COINBASE_API_KEY:
        missing.append("COINBASE_API_KEY")
    if not COINBASE_API_SECRET:
        missing.append("COINBASE_API_SECRET")
    if not COINBASE_API_SUB:
        missing.append("COINBASE_API_SUB")
    if not COINBASE_PEM_CONTENT:
        missing.append("COINBASE_PEM_CONTENT")

    if missing:
        logging.error(f"Cannot initialize Coinbase client. Missing keys: {missing}")
        return None

    # Import Coinbase client
    try:
        from coinbase_advanced_py import Client
    except ModuleNotFoundError:
        logging.error("coinbase_advanced_py module not installed.")
        return None

    # Initialize client
    try:
        coinbase_client = Client(
            key=COINBASE_API_KEY,
            secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_SUB,
            pem=COINBASE_PEM_CONTENT
        )
        logging.info("✅ Coinbase client initialized successfully.")
        return coinbase_client
    except Exception as e:
        logging.exception(f"Failed to initialize Coinbase client: {e}")
        return None

def test_coinbase_connection():
    client = get_coinbase_client()
    if not client:
        logging.warning("Coinbase client not initialized; cannot test connection.")
        return False

    try:
        accounts = client.get_accounts()
        logging.info(f"Connected to Coinbase. Accounts retrieved: {len(accounts)}")
        return True
    except Exception as e:
        logging.error(f"Coinbase connection test failed: {e}")
        return False

# Optional: run test automatically when module is loaded
if __name__ == "__main__":
    test_coinbase_connection()
