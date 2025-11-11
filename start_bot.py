from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        client = CoinbaseClient()
        logger.info("✅ CoinbaseClient initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to init CoinbaseClient: {e}")
        return

    accounts = client.fetch_accounts()
    if not accounts:
        logger.warning("No accounts found.")
    else:
        logger.info(f"Fetched {len(accounts)} accounts.")

if __name__ == "__main__":
    main()
