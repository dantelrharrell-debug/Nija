import os
import logging
from nija_client import CoinbaseClient  # Your wrapper around Coinbase Advanced API

# -------------------------
# Configure logging
# -------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# -------------------------
# Load environment variables
# -------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # PEM as string

# Quick sanity check
if not COINBASE_API_KEY or not COINBASE_ORG_ID or not COINBASE_PEM_CONTENT:
    logging.error("❌ Missing one or more Coinbase environment variables (API_KEY, ORG_ID, PEM_CONTENT)")
    exit(1)

# -------------------------
# Test Coinbase connection
# -------------------------
def test_coinbase_connection():
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            org_id=COINBASE_ORG_ID,
            pem_content=COINBASE_PEM_CONTENT
        )
        accounts = client.get_accounts()  # Fetch accounts to verify connection
        logging.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

# -------------------------
# Run the test
# -------------------------
if __name__ == "__main__":
    success = test_coinbase_connection()
    if success:
        logging.info("🎯 Connection test passed. You're ready to run the bot!")
    else:
        logging.error("💥 Connection test failed. Check your API_KEY, ORG_ID, and PEM_CONTENT.")
