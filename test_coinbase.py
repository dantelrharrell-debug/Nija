import os
import logging
from coinbase_advanced import CoinbaseAdvancedClient  # adjust import if you have custom client

logging.basicConfig(level=logging.INFO)

# Load environment variables
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_PEM_CONTENT]):
    logging.error("❌ One or more Coinbase environment variables are missing!")
    exit(1)

try:
    client = CoinbaseAdvancedClient(
        org_id=COINBASE_ORG_ID,
        api_key_id=COINBASE_API_KEY_ID,
        pem_content=COINBASE_PEM_CONTENT
    )
    accounts = client.get_accounts()  # simple read test
    logging.info(f"✅ Coinbase connection successful. Accounts fetched: {accounts}")
except Exception as e:
    logging.error(f"❌ Coinbase connection failed: {e}")
    exit(1)
