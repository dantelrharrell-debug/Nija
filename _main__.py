# main.py (or __main__.py)
import os
from loguru import logger
from nija_client import CoinbaseClient  # Ensure your cleaned class is in nija_client.py

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
    # Print account details
    for acct in accounts:
        logger.info(f"Account ID: {acct.get('id')} | Currency: {acct.get('currency')} | Balance: {acct.get('balance', {}).get('amount')}")

if __name__ == "__main__":
    main()
