from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust)...")
    client = CoinbaseClient()

    try:
        accounts = client.get_accounts()
        logger.info(f"Fetched accounts: {accounts}")

        positions = client.get_positions()
        logger.info(f"Fetched positions: {positions}")

        orders = client.get_orders()
        logger.info(f"Fetched orders: {orders}")

    except Exception as e:
        logger.error(f"Bot failed: {e}")

if __name__ == "__main__":
    main()
