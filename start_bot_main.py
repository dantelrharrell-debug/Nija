from loguru import logger
import time

def start_bot_main(client):
    """
    Main bot function.
    Uses the passed CoinbaseClient instance from main.py
    """
    logger.info("start_bot_main.py loaded")
    logger.info("Starting bot initialization...")

    # Example: fetch Coinbase accounts
    try:
        response = client.request("GET", "https://api.coinbase.com/v2/accounts")
        logger.info(f"Bot Coinbase accounts fetch: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"API response: {response.text}")
    except Exception as e:
        logger.exception("Failed to fetch accounts")

    # Bot logic loop
    while True:
        logger.info("Bot heartbeat - still running")
        time.sleep(10)
