# __main__.py
from app.nija_client import CoinbaseClient
from loguru import logger

def main():
    try:
        client = CoinbaseClient(advanced=True)
        accounts = client.fetch_advanced_accounts()
        logger.info(f"Accounts: {accounts}")
    except Exception as e:
        logger.exception(f"Failed to initialize or fetch accounts: {e}")

if __name__ == "__main__":
    main()
