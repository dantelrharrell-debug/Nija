# start_bot.py
from nija_client import CoinbaseClient
from loguru import logger

def main():
    logger.info("Starting Nija loader (robust).")
    
    # Initialize Coinbase client
    client = CoinbaseClient(base="https://api.coinbase.com/v2")
    logger.info("✅ CoinbaseClient initialized successfully.")

    try:
        # Fetch accounts using the updated method
        accounts = client.get_accounts()
        if accounts:
            logger.info(f"Fetched {len(accounts)} account(s): {accounts}")
        else:
            logger.warning("No accounts found.")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")

if __name__ == "__main__":
    main()
