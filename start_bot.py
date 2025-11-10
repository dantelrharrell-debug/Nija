# start_bot.py
import os
from loguru import logger
from app.nija_client import CoinbaseClient  # Use your robust shim

# ---------------- Logging Setup ----------------
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

# ---------------- Temp Debug: Show loaded env vars ----------------
logger.info(f"COINBASE_API_KEY: {os.getenv('COINBASE_API_KEY')}")
logger.info(f"COINBASE_ISS (Advanced): {os.getenv('COINBASE_ISS')}")
logger.info(f"COINBASE_BASE: {os.getenv('COINBASE_BASE')}")

# ---------------- Main ----------------
def main():
    logger.info("Starting Nija loader (robust).")

    # Try initializing CoinbaseClient (auto-detect advanced vs standard)
    try:
        # Pass advanced=True to prefer CDP/service key API
        client = CoinbaseClient(advanced=True)
    except Exception as e:
        logger.error(f"Error initializing CoinbaseClient: {e}")
        return

    # Try fetching accounts
    accounts = client.fetch_advanced_accounts()
    if not accounts:
        logger.warning("Advanced API returned no accounts; falling back to Spot API.")
        accounts = client.fetch_spot_accounts()

    if not accounts:
        logger.error("No accounts fetched. Check your COINBASE env vars and API permissions.")
        return

    # Successfully fetched accounts
    logger.info(f"Successfully fetched {len(accounts)} accounts.")
    for acct in accounts:
        logger.info(
            f"Account ID: {acct.get('id')} | "
            f"Currency: {acct.get('currency')} | "
            f"Balance: {acct.get('balance', {}).get('amount')}"
        )

# ---------------- Run ----------------
if __name__ == "__main__":
    main()
