import os
from loguru import logger
from nija_client import CoinbaseClient  # make sure this file exists and contains the class

# TEMP DEBUG: Check environment variables
logger.info(f"COINBASE_API_KEY: {os.getenv('COINBASE_API_KEY')}")
logger.info(f"COINBASE_API_KEY_ADVANCED: {os.getenv('COINBASE_API_KEY_ADVANCED')}")
logger.info(f"COINBASE_BASE: {os.getenv('COINBASE_BASE')}")

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def main():
    logger.info("Starting Nija loader (robust).")

    # Initialize client (auto-detects advanced vs spot)
    client = CoinbaseClient()

    # Try Advanced API first
    accounts = client.fetch_advanced_accounts()
    if not accounts:
        logger.warning("Advanced API failed; falling back to Spot API.")
        accounts = client.fetch_spot_accounts()

    if not accounts:
        logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        return

    logger.info(f"Successfully fetched {len(accounts)} accounts.")
    for acct in accounts:
        logger.info(
            f"Account ID: {acct.get('id')} | "
            f"Currency: {acct.get('currency')} | "
            f"Balance: {acct.get('balance', {}).get('amount')}"
        )

if __name__ == "__main__":
    main()
