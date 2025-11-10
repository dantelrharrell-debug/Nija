# start_bot.py
import time
from loguru import logger
from nija_client import CoinbaseClient

logger.info("Starting Nija bot — LIVE mode")

try:
    client = CoinbaseClient()
except Exception as e:
    logger.error(f"Failed to initialize CoinbaseClient: {e}")
    raise SystemExit("Cannot start bot without client.")

def fetch_balances():
    """
    Attempt to fetch accounts via Advanced API first,
    fallback to Classic API if Advanced fails.
    """
    accounts = client.get_accounts()
    if accounts:
        logger.info(f"[NIJA-BALANCE] Advanced API accounts: {accounts}")
        return accounts

    logger.warning("[NIJA-BALANCE] Advanced API failed, trying Classic API")
    accounts = client.get_classic_accounts()
    if accounts:
        logger.info(f"[NIJA-BALANCE] Classic API accounts: {accounts}")
        return accounts

    logger.warning("[NIJA-BALANCE] No accounts returned from either API")
    return None

def main_loop(poll_interval=10):
    """
    Main bot loop. Polls balances every `poll_interval` seconds.
    """
    while True:
        logger.info("Fetching balances...")
        balances = fetch_balances()
        if balances:
            for acc in balances.get("data", []):
                # Example: adjust this if Advanced vs Classic structure differs
                name = acc.get("name", "Unknown")
                balance = acc.get("balance", {}).get("amount", "0")
                currency = acc.get("balance", {}).get("currency", "USD")
                logger.info(f"Account: {name} — Balance: {balance} {currency}")
        else:
            logger.info("No balances fetched this tick.")

        time.sleep(poll_interval)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Nija bot stopped by user.")
    except Exception as e:
        logger.exception(f"Unhandled exception in main loop: {e}")
