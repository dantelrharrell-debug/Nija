# nija_client.py
import os
import logging
from coinbase_advanced.client import Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

_client = None  # global client instance

def get_coinbase_client():
    global _client
    if _client:
        return _client

    # Verify env vars
    missing = []
    for key in ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_SUB", "COINBASE_PEM_CONTENT"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        logging.error(f"Cannot initialize Coinbase client. Missing keys: {missing}")
        return None

    try:
        _client = Client(
            key=os.getenv("COINBASE_API_KEY"),
            secret=os.getenv("COINBASE_API_SECRET"),
            passphrase=os.getenv("COINBASE_API_SUB"),
            pem=os.getenv("COINBASE_PEM_CONTENT")
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
        logging.info(f"Coinbase connection test succeeded. Accounts retrieved: {len(accounts)}")
        return True
    except Exception as e:
        logging.error(f"Coinbase connection test failed: {e}")
        return False
