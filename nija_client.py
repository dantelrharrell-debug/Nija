import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

Client = None  # global lazy-loaded client

def get_coinbase_client():
    """Lazy initialization of Coinbase client."""
    global Client
    if Client:
        return Client

    # Check LIVE_TRADING
    live_trading = os.getenv("LIVE_TRADING", "0") == "1"
    if not live_trading:
        logging.warning("LIVE_TRADING disabled. Coinbase client will not be initialized.")
        return None

    # Required credentials
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_sub = os.getenv("COINBASE_API_SUB")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")
    pem_path = os.getenv("COINBASE_PEM_PATH")

    missing = []
    if not api_key: missing.append("COINBASE_API_KEY")
    if not api_secret: missing.append("COINBASE_API_SECRET")
    if not api_sub: missing.append("COINBASE_API_SUB")
    if not (pem_content or (pem_path and os.path.isfile(pem_path))):
        missing.append("COINBASE_PEM_CONTENT or COINBASE_PEM_PATH")

    if missing:
        logging.error(f"Cannot initialize Coinbase client. Missing: {missing}")
        return None

    # Load PEM
    pem = pem_content
    if not pem and pem_path:
        with open(pem_path, "r") as f:
            pem = f.read()

    try:
        from coinbase_advanced.client import Client as CBClient
        Client = CBClient(
            key=api_key,
            secret=api_secret,
            passphrase=api_sub,
            pem=pem
        )
        logging.info("✅ Coinbase client initialized successfully.")
        return Client
    except Exception as e:
        logging.exception(f"Failed to initialize Coinbase client: {e}")
        return None

def test_coinbase_connection():
    client = get_coinbase_client()
    if not client:
        logging.warning("Coinbase client not initialized; cannot test connection.")
        return
    try:
        accounts = client.get_accounts()
        logging.info(f"Connected to Coinbase. Accounts retrieved: {len(accounts)}")
    except Exception as e:
        logging.error(f"Coinbase connection test failed: {e}")

if __name__ == "__main__":
    test_coinbase_connection()
