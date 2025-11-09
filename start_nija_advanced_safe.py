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

# Load Advanced keys from environment variables
COINBASE_ISS = os.getenv("COINBASE_ISS", "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----""")

# Save PEM to a temp file
pem_path = "/tmp/coinbase.pem"
with open(pem_path, "w") as f:
    f.write(COINBASE_PEM_CONTENT)

# Initialize Advanced Coinbase client
client = CoinbaseClient(
    private_key_path=pem_path,
    iss=COINBASE_ISS,
    advanced=True
)

def fetch_accounts_safe():
    """Attempt to fetch v3 accounts, safely falling back if necessary"""
    endpoints = ["/v3/accounts", "/v2/accounts"]  # fallback order
    for path in endpoints:
        try:
            status, data = client.request(method="GET", path=path)
            if status == 200 and data:
                accounts_list = data.get("data", [])
                logger.info(f"✅ Fetched {len(accounts_list)} accounts from {path}")
                return accounts_list
            else:
                logger.warning(f"⚠️ {path} returned status {status}, trying next endpoint...")
        except Exception as e:
            logger.exception(f"Error fetching accounts from {path}: {e}")
    logger.error("❌ No accounts found after checking all endpoints.")
    return []

def main_loop():
    logger.info("Starting Advanced HMAC Coinbase bot...")
    while True:
        accounts = fetch_accounts_safe()
        if not accounts:
            logger.warning("No accounts found. Retrying in 10 seconds...")
            time.sleep(10)
            continue

        # Example: log balances
        for acc in accounts:
            balance = acc.get("balance", {}).get("amount", "N/A")
            currency = acc.get("currency", "N/A")
            acc_id = acc.get("id", "N/A")
            logger.info(f"Account: {acc_id}, Currency: {currency}, Balance: {balance}")

        time.sleep(30)  # poll every 30 seconds

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
