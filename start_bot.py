# start_bot.py
import time
from loguru import logger

# Import Coinbase client
try:
    from nija_client import CoinbaseClient
except ImportError as e:
    logger.error(f"Failed to import CoinbaseClient from nija_client: {e}")
    raise SystemExit("Cannot start bot without CoinbaseClient.")

logger.info("Starting Nija bot — LIVE mode")

# Initialize Coinbase client
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
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info(f"[NIJA-BALANCE] Advanced API accounts: {accounts}")
            return accounts
    except Exception as e:
        logger.warning(f"Advanced API fetch failed: {e}")

    logger.warning("[NIJA-BALANCE] Advanced API failed, trying Classic API")
    try:
        accounts = client.get_classic_accounts()
        if accounts:
            logger.info(f"[NIJA-BALANCE] Classic API accounts: {accounts}")
            return accounts
    except Exception as e:
        logger.warning(f"Classic API fetch failed: {e}")

    logger.warning("[NIJA-BALANCE] No accounts returned from either API")
    return None

def main_loop(poll_interval=10):
    """
    Main bot loop. Polls balances every `poll_interval` seconds.
    Runs continuously on Render without terminal interaction.
    """
    while True:
        try:
            logger.info("Fetching balances...")
            balances = fetch_balances()
            if balances:
                for acc in balances.get("data", []):
                    name = acc.get("name", "Unknown")
                    balance = acc.get("balance", {}).get("amount", "0")
                    currency = acc.get("balance", {}).get("currency", "USD")
                    logger.info(f"Account: {name} — Balance: {balance} {currency}")
            else:
                logger.info("No balances fetched this tick.")
        except Exception as e:
            logger.exception(f"Error during balance fetch: {e}")

        time.sleep(poll_interval)

if __name__ == "__main__":
    main_loop()
