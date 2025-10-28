# nija_client.py
import os
import logging
import threading
from coinbase_advanced_py import CoinbaseClient, CoinbaseError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

def load_coinbase_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    pem_file = os.getenv("COINBASE_API_PEM_FILE")  # optional
    pem_string = os.getenv("COINBASE_API_PEM_STRING")  # optional

    if not api_key or not api_secret:
        raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set.")

    # Load PEM key properly
    if pem_file:
        if not os.path.exists(pem_file):
            raise FileNotFoundError(f"PEM file not found at {pem_file}")
        client = CoinbaseClient(api_key=api_key, api_secret_file=pem_file)
    elif pem_string:
        # write temp PEM file for client
        import tempfile
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(pem_string)
            temp_path = f.name
        client = CoinbaseClient(api_key=api_key, api_secret_file=temp_path)
    else:
        client = CoinbaseClient(api_key=api_key, api_secret_file=None)

    try:
        accounts = client.get_accounts()
        logger.info(f"✅ Coinbase accounts fetched: {accounts}")
    except CoinbaseError as e:
        logger.error(f"Failed to fetch accounts: {e}")
        raise

    return client

def trading_loop(client):
    logger.info("🔥 Trading loop started 🔥")
    while True:
        # Put your live trading logic here
        # Example: fetch BTC price and print
        try:
            price = client.get_spot_price(currency_pair="BTC-USD")
            logger.info(f"BTC price: {price}")
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
        import time
        time.sleep(10)  # adjust frequency as needed

def start_trading():
    try:
        client = load_coinbase_client()
    except Exception as e:
        logger.error(f"Coinbase client failed to initialize: {e}")
        return

    # Run trading loop in background thread (avoids Render port issues)
    t = threading.Thread(target=trading_loop, args=(client,), daemon=True)
    t.start()
    logger.info("🔥 Nija trading loop is now live 🔥")
    t.join()  # keep main thread alive

if __name__ == "__main__":
    start_trading()
