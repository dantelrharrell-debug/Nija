from nija_client import CoinbaseClient
from loguru import logger

def main():
    logger.info("Starting Nija loader (robust)...")
    client = CoinbaseClient()

    try:
        accounts = client.get_accounts()
        logger.info("Accounts loaded successfully: %s", accounts)
    except Exception as e:
        logger.error("Failed to fetch accounts: %s", e)
        return

    # Example trading logic placeholder
    # You can replace this with your actual signal-based trade logic
    logger.info("Bot initialized. Ready for trading signals.")

if __name__ == "__main__":
    main()
