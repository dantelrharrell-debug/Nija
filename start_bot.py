# start_bot.py
import sys
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

# Add app folder to path (defensive if not installed as package)
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

try:
    from nija_client import CoinbaseClient
except Exception as e:
    logger.exception(f"Cannot import CoinbaseClient from nija_client: {e}")
    sys.exit(1)

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        # Turn on debug to see raw server body previews in logs
        client = CoinbaseClient(advanced=True, debug=True)

        # Try advanced first
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.warning("Advanced API failed; falling back to Spot API.")
            accounts = client.fetch_spot_accounts()

        if not accounts:
            logger.error("No accounts returned. Check COINBASE env vars, key permissions, IP allowlist, and COINBASE_BASE.")
            return

        logger.info(f"Successfully fetched {len(accounts)} accounts.")
        for acct in accounts:
            # safe printing - various API shapes exist
            name = acct.get("name") if isinstance(acct, dict) else str(acct)
            bal = acct.get("balance", {}) if isinstance(acct, dict) else {}
            logger.info(f" - {name} | {bal.get('amount', '?')} {bal.get('currency', '?')}")

    except Exception as e:
        logger.exception(f"Error initializing CoinbaseClient: {e}")

if __name__ == "__main__":
    main()
