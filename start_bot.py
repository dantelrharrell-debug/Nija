import sys
from loguru import logger
from nija_client import CoinbaseClient

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        client = CoinbaseClient()
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
            sys.exit(1)

        logger.info("Connected accounts:")
        for a in accounts:
            name = a.get("name", "<unknown>")
            bal = a.get("balance", {})
            logger.info(f" - {name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")

        logger.info("✅ Coinbase Advanced connection successful. Ready for trading loop.")

    except Exception as e:
        logger.exception(f"Error initializing CoinbaseClient: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
