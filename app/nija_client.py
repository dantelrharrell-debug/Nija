# # __main__.py (root)

import os
from loguru import logger
from app.nija_client import CoinbaseClient

def main():
    try:
        logger.info("Starting Nija Trading Bot...")

        # Initialize CoinbaseClient (Advanced / Service Key)
        client = CoinbaseClient(advanced=True)
        logger.info("CoinbaseClient initialized successfully.")

        # Test fetching accounts
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.error("No accounts returned. Check your API keys and environment variables.")
        else:
            logger.info(f"Fetched {len(accounts)} accounts successfully:")
            for acc in accounts:
                logger.info(f" - {acc.get('name')} ({acc.get('id')})")

        # Place for live trading logic
        # Example: client.request("POST", "/orders", data={...})

    except Exception as e:
        logger.exception(f"Failed to start bot: {e}")

if __name__ == "__main__":
    main()
