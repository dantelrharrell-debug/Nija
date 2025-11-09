from nija_hmac_client import CoinbaseClient

from loguru import logger
from nija_hmac_client import CoinbaseClient

logger.info("🚀 Starting NIJA HMAC live bot...")

def fetch_accounts():
    client = CoinbaseClient()
    status, accounts = client.request("GET", "/v2/accounts")

    if status != 200:
        logger.error(f"❌ Failed to fetch accounts. Status: {status} | Response: {accounts}")
        return
    logger.info("✅ Accounts fetched:")
    for acct in accounts.get("data", []):
        logger.info(f"{acct['name']} ({acct['currency']}): {acct['balance']['amount']}")

if __name__ == "__main__":
    fetch_accounts()
