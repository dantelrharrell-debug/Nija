# check_account.py
from nija_client import CoinbaseClient
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

if __name__ == "__main__":
    try:
        client = CoinbaseClient(advanced=True)
        accounts = client.fetch_advanced_accounts()

        if not accounts:
            logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        else:
            logger.info("Connected accounts:")
            for a in accounts:
                name = a.get("name", "<unknown>")
                bal = a.get("balance", {})
                logger.info(f" - {name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")

    except Exception as e:
        logger.exception(f"Error fetching accounts: {e}")
