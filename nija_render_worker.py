import logging
import time

logger = logging.getLogger("nija_worker")

def start_worker(client):
    """
    Start the Nija trading worker using the given client.
    :param client: Either CoinbaseClient (live) or DummyClient
    """
    logger.info("[NIJA] Starting Nija worker...")

    # Example loop — replace with your actual trading logic
    while True:
        try:
            # Example: fetch account balances
            balances = client.get_account_balances()  # adjust to your client's API
            logger.info(f"[NIJA] Current balances: {balances}")

            # Example: run trading logic here
            # client.place_order(...)

            time.sleep(10)  # adjust frequency as needed
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted by user. Exiting.")
            break
        except Exception as e:
            logger.error(f"[NIJA] Worker encountered an error: {e}")
            time.sleep(5)  # short pause before retry
