from loguru import logger
import time

def start_bot_main(client):
    """
    Main bot function.
    Uses the passed CoinbaseClient instance.
    """
    logger.info("start_bot_main.py loaded")
    logger.info("Starting bot initialization...")

    # Example: fetch Coinbase accounts
    try:
        response = client.request("GET", "https://api.coinbase.com/v2/accounts")
        logger.info(f"Bot Coinbase accounts fetch: {response.status_code}")
    except Exception as e:
        logger.exception("Failed to fetch accounts")

    # Your bot logic here
    while True:
        logger.info("Bot heartbeat - still running")
        time.sleep(10)
