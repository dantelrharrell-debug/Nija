import sys
from loguru import logger
from nija_client import CoinbaseClient

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def main():
    logger.info("Starting Nija loader (robust).")

    # Try Advanced first
    client = CoinbaseClient(advanced=True)
    accounts = client.fetch_advanced_accounts()

    # Fallback to Spot API if advanced failed
    if not accounts:
        logger.warning("Advanced API failed; falling back to Spot API.")
        client = CoinbaseClient(advanced=False)
        accounts = client.get_accounts()

    if not accounts:
        logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        sys.exit(1)

    logger.info("Connected accounts:")
    for a in accounts:
        name = a.get("name", "<unknown>")
        bal = a.get("balance", {})
        logger.info(f" - {name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")

    logger.info("✅ Coinbase connection verified. Bot ready to trade.")

if __name__ == "__main__":
    main()
