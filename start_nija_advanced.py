import os
import json
import time
import logging
from nija_client import CoinbaseClient  # your Advanced client

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Load your Advanced keys from environment variables
COINBASE_ISS = os.getenv("COINBASE_ISS", "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----""")

# Save PEM to a file for the client
pem_path = "/tmp/coinbase.pem"
with open(pem_path, "w") as f:
    f.write(COINBASE_PEM_CONTENT)

# Initialize Advanced Coinbase client
client = CoinbaseClient(
    private_key_path=pem_path,
    iss=COINBASE_ISS,
    advanced=True
)

def fetch_advanced_accounts():
    """Fetch accounts via v3 endpoint, safely"""
    try:
        status, data = client.request(method="GET", path="/v3/accounts")  # strictly v3
        if status != 200 or not data:
            logger.error(f"❌ Failed to fetch accounts. Status: {status}")
            return []
        accounts_list = data.get("data", [])
        logger.info(f"✅ Fetched {len(accounts_list)} accounts.")
        return accounts_list
    except Exception as e:
        logger.exception(f"Failed to fetch accounts: {e}")
        return []

def main_loop():
    logger.info("Starting Coinbase Advanced HMAC bot...")
    while True:
        accounts = fetch_advanced_accounts()
        if not accounts:
            logger.warning("No accounts found. Retrying in 10 seconds...")
            time.sleep(10)
            continue

        # Example: log balances
        for acc in accounts:
            logger.info(f"Account: {acc.get('id')}, Currency: {acc.get('currency')}, Balance: {acc.get('balance', {}).get('amount')}")

        # Wait before next poll
        time.sleep(30)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
