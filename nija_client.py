import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Lazy-loaded global client
_client = None

def get_coinbase_client():
    """Return a Coinbase client instance if LIVE_TRADING is enabled."""
    global _client
    if _client:
        return _client

    if os.getenv("LIVE_TRADING", "0") != "1":
        logging.warning("LIVE_TRADING disabled. Coinbase client not initialized.")
        return None

    # Load credentials from environment variables
    key = os.getenv("COINBASE_API_KEY")
    secret = os.getenv("COINBASE_API_SECRET")
    sub = os.getenv("COINBASE_API_SUB")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")

    missing = [k for k, v in [("COINBASE_API_KEY", key), ("COINBASE_API_SECRET", secret),
                              ("COINBASE_API_SUB", sub), ("COINBASE_PEM_CONTENT", pem_content)] if not v]

    if missing:
        logging.error(f"Cannot initialize Coinbase client. Missing keys: {missing}")
        return None

    # Import here to avoid ModuleNotFoundError if package missing
    try:
        from coinbase_advanced_py.client import Client
        _client = Client(
            key=key,
            secret=secret,
            passphrase=sub,
            pem=pem_content
        )
        logging.info("✅ Coinbase client initialized successfully.")
        return _client
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
