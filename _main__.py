import os
from loguru import logger
from nija_client import CoinbaseClient  # Make sure this points to your nija_client.py

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def main():
    logger.info("Starting Nija loader (robust).")

    # Initialize client (auto-detects advanced vs spot)
    try:
        client = CoinbaseClient(debug=True)  # set debug=False to reduce logging
    except ValueError as e:
        logger.error(f"Initialization failed: {e}")
        return

    # Attempt to fetch accounts: Advanced first, fallback to Spot
    accounts = client.fetch_advanced_accounts()
    if not accounts and not client.advanced:  # If advanced failed or not available
        logger.warning("Advanced API failed or unavailable; trying Spot API.")
        accounts = client.fetch_spot_accounts()

    if not accounts:
        logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        return

    logger.info(f"Successfully fetched {len(accounts)} accounts.")

    # Print account details
    for acct in accounts:
        acct_id = acct.get("id", "N/A")
        currency = acct.get("currency", "N/A")
        balance = acct.get("balance", {}).get("amount") if isinstance(acct.get("balance"), dict) else "N/A"
        logger.info(f"Account ID: {acct_id} | Currency: {currency} | Balance: {balance}")

if __name__ == "__main__":
    main()
