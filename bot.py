# bot.py
import os
import logging
import time
from nija_client import get_coinbase_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija-bot")

def find_funded_account(client, account_id):
    accounts = client.get_accounts()
    if not accounts:
        return None
    return next((a for a in accounts if a.get("id") == account_id), None)

def main():
    account_id = os.getenv("COINBASE_ACCOUNT_ID")
    if not account_id:
        logger.error("Missing COINBASE_ACCOUNT_ID environment variable")
        raise SystemExit("Set COINBASE_ACCOUNT_ID")

    client = get_coinbase_client()

    # quick check
    funded = find_funded_account(client, account_id)
    if not funded:
        logger.error("Funded account ID not visible to API. Check keys & account id.")
        raise SystemExit("Funded account not found")

    logger.info(f"Connected. Funded acct {funded.get('currency')} balance: {funded.get('balance')['amount']}")

    # Simple loop placeholder (replace with your trading logic)
    try:
        while True:
            # Example: poll accounts and log balance
            accounts = client.get_accounts()
            acct = next((a for a in accounts if a.get("id") == account_id), None)
            logger.info(f"[heartbeat] Balance: {acct.get('balance')['amount']}")
            # TODO: insert trading logic here (entry/exit)
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Shutting down bot (KeyboardInterrupt)")

if __name__ == "__main__":
    main()
