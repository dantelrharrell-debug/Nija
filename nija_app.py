from nija_client import CoinbaseClient
from loguru import logger

def main():
    try:
        client = CoinbaseClient()
        client.validate_coinbase()
        logger.info("Bot started successfully!")
        # Place your trading logic here
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")

if __name__ == "__main__":
    main()
