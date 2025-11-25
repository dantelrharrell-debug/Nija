import os
import time
import logging
from coinbase_advanced.client import Client  # Official package

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Load Coinbase credentials from environment variables
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# Connection retry settings
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds

def create_client():
    """Initialize Coinbase client safely."""
    try:
        return Client(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            pem_content=COINBASE_PEM_CONTENT
        )
    except Exception as e:
        logging.error(f"❌ Failed to initialize Coinbase client: {e}")
        return None

client = create_client()

def fetch_accounts():
    """Fetch all Coinbase accounts with retries."""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            accounts = client.get_accounts()
            logging.info(f"✅ Coinbase accounts fetched: {accounts}")
            return accounts
        except Exception as e:
            retries += 1
            logging.warning(f"⚠️ Coinbase fetch attempt {retries} failed: {e}")
            time.sleep(RETRY_DELAY)
    logging.error(f"❌ Failed to fetch accounts after {MAX_RETRIES} attempts.")
    return None

def test_coinbase_connection():
    """Verify Coinbase connection with retries."""
    logging.info("Testing Coinbase connection...")
    accounts = fetch_accounts()
    if accounts:
        logging.info("✅ Coinbase connection verified successfully.")
        return True
    else:
        logging.error("❌ Coinbase connection failed after multiple retries.")
        return False

if __name__ == "__main__":
    # Run a connection test when the module is executed directly
    test_coinbase_connection()
