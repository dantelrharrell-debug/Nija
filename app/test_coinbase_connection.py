import logging
from app.nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)

def test_coinbase_connection():
    try:
        client = CoinbaseClient()
        accounts = client.fetch_accounts()
        logging.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

if __name__ == "__main__":
    test_coinbase_connection()
