import sys
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

try:
    from nija_client import CoinbaseClient
except ImportError as e:
    logger.error(f"Cannot import CoinbaseClient: {e}")
    sys.exit(1)

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        client = CoinbaseClient(advanced=True)
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.warning("Advanced API failed; falling back to Spot API.")
            accounts = client.fetch_spot_accounts()
        if not accounts:
            logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
            sys.exit(1)

        logger.info("Connected accounts:")
        for a in accounts:
            name = a.get("name", "<unknown>")
            bal = a.get("balance", {})
            logger.info(f" - {name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")

        logger.info("✅ Coinbase connection verified. Bot ready to trade (trading loop not included here).")

    except Exception as e:
        logger.exception(f"Error initializing CoinbaseClient: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
