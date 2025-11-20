# nija_render_worker.py - main bot loop example
import logging
from time import sleep
from nija_client import get_coinbase_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_worker")

def main_loop():
    client = get_coinbase_client()

    # test accounts
    try:
        accounts = client.get_accounts()
        logger.info("Accounts fetched: %d", len(accounts))
        # optionally identify funded account
        acct_id = __import__("os").environ.get("COINBASE_ACCOUNT_ID")
        if acct_id:
            funded = next((a for a in accounts if a.get("id")==acct_id), None)
            if funded:
                logger.info("Found funded account: %s balance=%s", funded.get("currency"), funded.get("balance",{}).get("amount"))
            else:
                logger.warning("Funded account id not found in accounts list")
    except Exception as e:
        logger.exception("Failed to fetch accounts: %s", e)
        raise

    logger.info("⚡ Entering trading loop (placeholder).")
    while True:
        try:
            # TODO replace this with your live-trading logic: signals -> place orders via client
            logger.info("Tick - checking market (placeholder).")
            sleep(10)
        except Exception as e:
            logger.exception("Error in trading loop: %s", e)
            sleep(5)

if __name__ == "__main__":
    main_loop()
