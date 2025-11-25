import os
import time
import logging

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# --- Try importing coinbase_advanced ---
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logger.error("coinbase_advanced module not installed.")

# --- Environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# --- Retry settings ---
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds

# --- Client creation ---
def create_client():
    if not Client:
        logger.error("Cannot create client: coinbase_advanced is missing.")
        return None
    if not COINBASE_API_KEY or not COINBASE_API_SECRET:
        logger.error("COINBASE_API_KEY or COINBASE_API_SECRET missing.")
        return None
    try:
        client = Client(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            pem_content=COINBASE_PEM_CONTENT
        )
        logger.info("Coinbase client created successfully.")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
        return None

# --- Wrapper class for main.py usage ---
class CoinbaseClientWrapper:
    def __init__(self):
        self.client = create_client()

    def get_accounts(self):
        """Fetch Coinbase accounts with retries."""
        if not self.client:
            logger.error("Client not initialized.")
            return None

        retries = 0
        while retries < MAX_RETRIES:
            try:
                accounts = self.client.get_accounts()
                logger.info(f"Coinbase accounts fetched: {accounts}")
                return accounts
            except Exception as e:
                retries += 1
                logger.warning(f"Attempt {retries} failed: {e}")
                time.sleep(RETRY_DELAY)

        logger.error(f"Failed to fetch accounts after {MAX_RETRIES} attempts.")
        return None

    def test_connection(self):
        """Test if Coinbase connection works."""
        accounts = self.get_accounts()
        if accounts:
            logger.info("Coinbase connection verified successfully.")
            return True
        logger.error("Coinbase connection failed.")
        return False

# --- Export for main.py ---
CoinbaseClient = CoinbaseClientWrapper

# --- Self-test when run directly ---
if __name__ == "__main__":
    client = CoinbaseClient()
    success = client.test_connection()
    exit(0 if success else 1)
