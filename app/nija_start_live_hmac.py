# nija_start_live_hmac.py
from loguru import logger
logger.info("STARTUP: Running nija_start_live_hmac.py (HMAC entrypoint)")

from nija_hmac_client import CoinbaseClient
import os

def fetch_accounts():
    try:
        client = CoinbaseClient()
        status, accounts = client.request(method="GET", path="/v2/accounts")

        if status != 200:
            logger.error(f"❌ Failed to fetch accounts. Status: {status}")
            return []
        else:
            logger.info("✅ Accounts fetched:")
            for acct in accounts.get("data", []):
                logger.info(f"{acct['name']} ({acct['currency']}): {acct['balance']['amount']}")
            return accounts.get("data", [])
    except Exception as e:
        logger.exception(f"❌ Error fetching accounts: {e}")
        return []

if __name__ == "__main__":
    required_vars = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing = [v for v in required_vars if v not in os.environ]
    if missing:
        logger.error(f"Missing environment variables: {missing}")
    accounts = fetch_accounts()
    if not accounts:
        logger.warning("No accounts available. Check HMAC key permissions.")
