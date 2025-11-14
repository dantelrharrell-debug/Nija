# app/nija_client.py

import os
from coinbase.rest import RESTClient  # Coinbase SDK
from loguru import logger

# 1️⃣ Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

# 2️⃣ Fix PEM newlines if Railway converted them to literal \n
if PEM_RAW and "\\n" in PEM_RAW:
    PEM_RAW = PEM_RAW.replace("\\n", "\n")

# 3️⃣ Initialize Coinbase REST client
try:
    client = RESTClient(
        api_key=API_KEY,
        api_secret=PEM_RAW,
    )
    logger.info("✅ Coinbase REST client initialized successfully.")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase client: {e}")
    client = None

# 4️⃣ Test function to list accounts
def test_accounts():
    if not client:
        logger.error("Coinbase client not initialized.")
        return None
    try:
        accounts = client.get_accounts()
        logger.info("✅ Accounts fetched successfully.")
        return accounts.data
    except Exception as e:
        logger.error(f"❌ Failed to fetch accounts: {e}")
        return None

# Optional: run test on startup
if __name__ == "__main__":
    accounts = test_accounts()
    if accounts:
        for a in accounts:
            print(a)
