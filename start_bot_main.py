# start_bot_main.py

import os
import time
from loguru import logger
from nija_client import CoinbaseClient
from requests.exceptions import HTTPError, ConnectionError, Timeout

# Retry settings
RETRY_DELAY = 5       # seconds between retries
MAX_RETRIES = 5       # max retry attempts per request

def safe_request(func, *args, **kwargs):
    """Wrapper to retry API requests on transient errors."""
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            if e.response.status_code in [404, 429, 500, 502, 503, 504]:
                logger.warning(f"HTTP {e.response.status_code} error, retrying in {RETRY_DELAY}s...")
                attempt += 1
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"HTTP error: {e}")
                raise
        except (ConnectionError, Timeout) as e:
            logger.warning(f"Connection error: {e}, retrying in {RETRY_DELAY}s...")
            attempt += 1
            time.sleep(RETRY_DELAY)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise
    raise RuntimeError(f"Max retries reached for {func.__name__}")

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        client = CoinbaseClient()
        logger.info("CoinbaseClient initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize CoinbaseClient: {e}")
        return

    while True:
        try:
            # --- Get accounts ---
            accounts = safe_request(client.get_accounts)
            logger.info(f"Accounts fetched: {accounts}")

            if not accounts or len(accounts) == 0:
                logger.error("No accounts found, retrying...")
                time.sleep(RETRY_DELAY)
                continue

            account_id = accounts[0]["id"]
            logger.info(f"Using account_id={account_id}")

            # --- Get positions ---
            positions = safe_request(client.get_positions)
            logger.info(f"Positions fetched: {positions}")

            # --- Example: Place a market order ---
            side = "buy"
            product_id = "BTC-USD"
            size = "0.001"

            logger.info(f"Placing order: {side} {size} {product_id}")
            order = safe_request(client.place_order, account_id, side, product_id, size)
            logger.info(f"Order response: {order}")

            # --- Fetch order status ---
            order_id = order.get("id")
            if order_id:
                status = safe_request(client.get_order, order_id)
                logger.info(f"Order status: {status}")
            else:
                logger.warning("No order ID returned, cannot fetch status")

            # Wait before next loop
            logger.info(f"Cycle complete. Waiting {RETRY_DELAY}s before next iteration...")
            time.sleep(RETRY_DELAY)

        except Exception as e:
            logger.error(f"Error during bot run: {e}")
            logger.info(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    main()
