from nija_client import CoinbaseClient
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def main():
    logger.info("Checking Coinbase accounts...")

    client = CoinbaseClient(advanced=True)
    accounts = client.fetch_advanced_accounts()

    if not accounts:
        logger.warning("Advanced API failed; trying Spot API.")
        client = CoinbaseClient(advanced=False)
        accounts = client.get_accounts()

    if not accounts:
        logger.error("No accounts found. Check API key and permissions.")
        return

    logger.info("Accounts:")
    for a in accounts:
        name = a.get("name", "<unknown>")
        bal = a.get("balance", {})
        logger.info(f" - {name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")

if __name__ == "__main__":
    main()
